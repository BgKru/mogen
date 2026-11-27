# Increment 13 close-out review — advanced object generation

**Date:** 2026-11-25
**Specification:** [`docs/additions/13_advanced_object_generation.md`](../additions/13_advanced_object_generation.md)
**Plan and acceptance criteria:** [`docs/additions/13_implementation_plan.md`](../additions/13_implementation_plan.md)
**Scope:** one post-MVP increment. TripoSR remains the default and the
regression baseline; Stable Fast 3D is an opt-in generator behind a small
contract; Hunyuan3D is gated and documented as blocked.

## 1. Summary

The increment adds a typed generator contract, an explicit factory, validated
per-generator configuration, an isolated Stable Fast 3D adapter with manifest-
verified weights, output normalization for UV/textured assets, a textured GLB
export/validation path, a generator metadata block, pre-inference fallback, an
opt-in Compose overlay and image target, CPU unit tests and a reproducible
benchmark runner. No public API, frontend, task lifecycle, viewer, result
contract, outbox or reconstruction algorithm was changed.

Real SF3D inference is **blocked** on gated model access: the weights live in
the gated `stabilityai/stable-fast-3d` repository. Anonymous requests return 401
and the Hugging Face token available on this host returns 403 for both
`config.yaml` and `model.safetensors`; the initializer run reproduces this with a
`GatedRepoError` and a user-safe message. The image target, manifest
verification, adapter, normalization and textured export are implemented and
unit/fixture-verified; the real-weight load, inference, benchmark and live task
are reported as blocked rather than simulated. Hunyuan3D is blocked after the
licence/territory and hardware review.

**Update (2026-11-26):** the gate is resolved. A classic read token from the
account that had accepted the Stability AI Community License returns HTTP 200
for `config.yaml` and `model.safetensors`; the initializer populated
`/models/sf3d`, the real inference tests passed, a live SF3D task completed
through the API, the browser viewer loaded the textured GLB, and the
TripoSR/SF3D benchmark ran 12/12 for both generators. Section 8 records the
evidence and the three defects that only the real run could expose.

## 2. Compatibility findings

| Item | Value |
|---|---|
| SF3D source | commit `ff21fc491b4dc5314bf6734c7c0dabd86b5f5bb2` (2025-01-22) |
| SF3D weights | `stabilityai/stable-fast-3d` revision `f0c9a8ffd62cb1bbc8a7a53c9f87a0be1b6be778`; `config.yaml` + `model.safetensors` (3.84 GB) |
| Access | gated (`gated: auto`); anonymous download 401, cached OAuth token 403 on 2026-11-25; a classic read token returns 200 since 2026-11-26 (Section 8) |
| Licence | Stability AI Community License (source and weights) |
| Runtime | Python 3.12.3, torch 2.14.1+cu126, CUDA 12.6, RTX 3060 12 GB |
| Conflict | upstream pins `numpy==1.26.4`, `transformers==4.42.3`, `trimesh==4.4.1`, `huggingface-hub==0.23.4`, `rembg==2.0.57`; the TripoSR image already has `numpy 2.3.5`, `transformers 4.46.3`, `trimesh 4.12.2`, `hub 0.26.2`, `rembg 2.0.87` |
| Resolution | install only the missing packages into `/opt/sf3d-site` with `--no-deps` and put that directory first on `PYTHONPATH`; the TripoSR site-packages are untouched. A spike proved SF3D imports with the newer stack (the remaining import failure was `uv_unwrapper`, which is built in the image) |
| gpytoolbox | upstream `0.2.0` has no CPython 3.12 wheel; pinned `0.3.8`, which is only used by the optional remesh paths |
| Native extensions | `texture_baker` (CUDAExtension) and `uv_unwrapper` (CppExtension) compile in the devel-based `sf3d-native-build` stage and are installed as wheels |

The first SF3D image build exposed an import-shadowing defect: the upstream
checkout has no `sf3d/__init__.py`, so a checkout placed at `/opt/sf3d` is a
namespace package that loses to the ComfyUI root `__init__.py` when `/opt` is on
`PYTHONPATH`. The source is therefore mounted at `/opt/sf3d-src` and the build
preflight imports `sf3d.system`, `texture_baker.TextureBaker` and
`uv_unwrapper.Unwrapper` in the final image. The rebuilt
`mogen-object-worker:sf3d` passed the preflight with
`sf3d preflight ok: 2.14.1+cu126 SF3D TextureBaker Unwrapper`; a direct import
check in the image reports `2.14.1+cu126`, numpy `2.3.5`, trimesh `4.12.2`.
`pip check` in that image is **not** clean: the isolated set shadows scipy and
scikit-image (three declared-range mismatches, Section 6).

## 3. Implemented

**New files:** `generator_base.py` (protocol, capabilities, result type),
`generator_factory.py` (allowlist, process-wide cache, blocked-name errors),
`normalization.py` (appearance-aware validation), `sf3d/{__init__,adapter,loader,download_models}.py`,
`requirements-sf3d.txt`, `benchmarks/run_benchmark.py`, `compose.sf3d.yaml`,
four CPU test modules, one opt-in real test and `.proof/increment13/` evidence.

**Modified:** `config.py` (generator/SF3D config and validation),
`pipeline.py` (generator dispatch, capability-driven preprocessing, fallback,
normalization, metadata), `generator.py` (TripoSR adapter, CUDA peak
measurement, `release_model`), `model_loader.py`, `exporter.py` (textured path),
`validator.py` (embedded base-colour texture + UV acceptance),
`mesh_processor.py` (texture/UV facts), `preprocessing.py`
(`prepare_rgba_input`), `exceptions.py` (generator-neutral codes),
`backend/app/core/config.py` (validated settings, Hunyuan3D gate),
`backend/app/tasks/object_pipeline.py` (configured-generator bootstrap),
`compose.yaml` (generator env), `.env.example`, `.env.production.example`,
`ml/object_generation/README.md`, the object-generation tests and the plan.

**Behaviour:**

- `OBJECT_GENERATOR` defaults to `triposr`. The TripoSR model, preprocessing,
  stage reporting, mesh validation, vertex-colour export and cache are reused
  unchanged through a thin adapter.
- The SF3D adapter verifies `model-manifest.json` (per-file SHA-256, pinned model
  id and revision) before loading, runs `SF3D.run_image` on the RGBA image the
  shared pipeline prepared, records inference/postprocessing time and the
  measured CUDA peak, and never downloads during a task.
- `OBJECT_GENERATOR_FALLBACK=true` allows a pre-inference fallback to TripoSR
  and records `generator.fallback {used, reason, requested_generator,
  actual_generator}`. A failure after inference starts is a task error.
- Preprocessing runs exactly once per task: TripoSR receives the 512 px RGB
  composite, SF3D the RGBA foreground; neither adapter repeats rembg.
- Normalization accepts vertex colours or a textured PBR material, rejects
  missing UVs/textures, non-finite values and multi-part scenes, and records
  `coordinate_system: y_up`. The exporter keeps the TripoSR path unchanged and
  embeds the texture for the textured path. The validator accepts `COLOR_0` or
  an embedded `baseColorTexture` with `TEXCOORD_0`; neither is still a failure.
- Result metadata gains a `generator` block (name, source revision, model
  id/revision, timings, `preprocessing_profile`, texture resolution/remesh,
  peak CUDA bytes when measured) plus `preprocessing_capabilities` and
  `normalization`. No paths, tokens or tracebacks are exposed.
- Hunyuan3D cannot be selected: the settings validate its licence
  acknowledgement, excluded territory, shape-only mode and disabled texture
  generation, then refuse the adapter because it is not installed.

## 4. Requirement traceability

| ID | Result | Evidence |
|---|---|---|
| I13-AC-01 | Passed | Real TripoSR inference test passed with the new pipeline (1 passed); object suite green; vertex-colour export test retained |
| I13-AC-02 | Passed | Settings default test; TripoSR path needs no new download; real test used the existing cache |
| I13-AC-03 | Passed (completed 2026-11-26) | Config/factory/pipeline selection and a valid textured GLB are proven with the fixture and with the real weights; a live SF3D task produced a 664 464-byte textured GLB (Section 8) |
| I13-AC-04 | Passed (completed 2026-11-26) | UVs/material/texture survive normalization and export; Khronos validator 0 errors (1 tangent-space warning) on the live GLB; the real Edge viewer loaded it with 2 embedded textures (Section 8) |
| I13-AC-05 | Passed | Metadata tests and fixture metadata plus live SF3D metadata (generator block, pinned revisions, timings, peak CUDA bytes) in Section 8 |
| I13-AC-06 | Passed (completed 2026-11-26) | Manifest mismatch/missing/revision tests; separate `/models/sf3d` cache populated and checksum-verified; the initializer also seeds the DINOv2/CLIP caches the offline worker needs (Section 8) |
| I13-AC-07 | Passed (completed 2026-11-26) | Concurrency 1, one adapter per process; TripoSR benchmark peak 4.45 GB; SF3D peak 5.44 GB allocated / 6.64 GB reserved on the RTX 3060 (Section 8) |
| I13-AC-08 | Passed | Defaults disabled; licence/territory/mode/texture gates and factory rejection tests |
| I13-AC-09 | **Blocked** | Adapter not installed; documented, never bypassed |
| I13-AC-10 | Passed | `shape_texture` rejected; `object_hunyuan3d_texture_enabled=true` rejected |
| I13-AC-11 | Passed | Backend **552 passed**; live GPU TripoSR task `COMPLETED` through the API with the new pipeline (1 528 660-byte GLB, device `cuda:0`, generator metadata present); stages/cancellation/result tests unchanged |
| I13-AC-12 | Passed (completed 2026-11-26) | CPU suites pass (object **135 passed, 3 skipped**; backend **573**); object suite also passes in the SF3D image; TripoSR benchmark 12/12 and SF3D benchmark 12/12 (Section 8) |
| I13-AC-13 | Passed | No route, schema, viewer or frontend change |
| I13-AC-14 | Passed | Unknown/disabled/blocked generator rejection tests |
| I13-AC-15 | Passed | Single-pass preprocessing test (`rembg` exactly once, RGBA path only) |
| I13-AC-16 | Passed | OOM mapping, invalid-image error, fallback/no-fallback, cancellation and normalization-rejection tests |

## 5. Verification executed

Baseline before any change (2026-11-25):

| Check | Result |
|---|---|
| Development stack | nine services healthy; workers answer `celery inspect ping`; dispatcher/recovery heartbeats fresh |
| Migration | `alembic current` = `1f302d830cf9 (head)` |
| Scene ML suite | **117 passed, 2 skipped** (119 collected; the earlier "119 passed" wording over-counted by two) |
| Image-quality suite | **47 passed** |
| Backend suite | **541 passed** |

After the change:

| Check | Result |
|---|---|
| Object ML suite (CPU) | **76 passed, 3 skipped** (opt-in real TripoSR and the two SF3D real tests) |
| Real TripoSR inference | **1 passed** through the new pipeline |
| Backend suite | **552 passed** (541 baseline + 11 new settings cases) |
| Ruff (object generation) | clean for changed files; 3 pre-existing `I001` in untouched test modules remain (4 before; one fixed in an edited file) |
| Ruff (backend changed files) | clean |
| `pip check` (object image) | clean |
| Compose validation | `compose.yaml`, the SF3D overlay and the production overlay all `config -q` |
| Khronos glTF Validator (textured fixture) | **0 errors, 0 warnings**, `hasTextures: true` |
| TripoSR benchmark | 12/12 successful runs, median 5.545 s, p95 12.53 s, mean 2 048 538 bytes, 51 246 vertices / 102 298 faces, peak 4.45 GB |
| SF3D image build (`--target sf3d`) | **succeeded**; `mogen-object-worker:sf3d` `sha256:dfe3aac2d74b…`, 13.8 GB; both native wheels compiled in the devel stage; isolated deps installed |
| SF3D image preflight | `sf3d preflight ok: 2.14.1+cu126 SF3D TextureBaker Unwrapper` |
| SF3D image import check | `sf3d`, `sf3d.system`, `texture_baker`, `uv_unwrapper` import; torch 2.14.1+cu126, numpy 2.3.5, trimesh 4.12.2 |
| Object suite inside the SF3D image | **76 passed, 3 skipped** |
| `pip check` in the SF3D image | **fails**: 3 declared-range mismatches in the isolated dependency set (Section 6) |
| SF3D weight initializer | **blocked**: `GatedRepoError`, user-safe message, no token logged, no weights written |
| Live TripoSR task (default worker, rebuilt image, GPU) | **COMPLETED** through the API in ~20 s: 1 528 660-byte GLB, **device `cuda:0`**, inference 4.165 s, extraction 6.147 s, peak CUDA allocated 4.44 GB / reserved 5.58 GB, `generator.name=triposr`, pinned source/model revisions, normalization and preprocessing capabilities in the result metadata, no paths or tensors |
| Live TripoSR task (CPU configuration, no GPU override) | **COMPLETED**: 1 528 688-byte GLB, device `cpu`, inference 10.235 s, extraction 17.499 s; proves the CPU fallback path still works |

The default `object-worker` was rebuilt from the updated source and recreated
with the GPU override; it reports healthy and logged
`object_generation_pipeline_ready`. The CPU run above was an accidental but
useful check of `OBJECT_DEVICE=cpu` before the override was reapplied.

### 5.1 Blocked checks and how they were resolved (2026-11-26)

- `python -m object_generation.sf3d.download_models` inside
  `mogen-object-worker:sf3d` could not download `config.yaml` /
  `model.safetensors`: the repository is gated and returned 403 for the token in
  `~/.cache/huggingface/token`.
- Resolution: sign in on Hugging Face with the account that owns the token, open
  <https://huggingface.co/stabilityai/stable-fast-3d>, accept the Stability AI
  Community License, create a **classic read token**, and pass it as `HF_TOKEN`.
  The token used on 2026-11-26 returns HTTP 200 for both files. All three
  follow-up steps (initializer, real test, live task, benchmark) were executed;
  see Section 8.

## 6. Known limitations

- Real SF3D weights/inference/benchmark and the live SF3D task were blocked when
  this review was written (2026-11-25); they were completed on 2026-11-26 and are
  recorded with their caveats in Section 8.
- `pip check` in `mogen-object-worker:sf3d` reports three declared-range
  mismatches in the isolated dependency set: `gpytoolbox 0.3.8` wants
  `scipy<=1.17.1` (runtime 1.18.1), `ftfy 6.2.3` wants `wcwidth<0.3` (runtime
  0.9.1), and `rembg 2.0.87` wants `scikit-image>=0.26` (the target shadows
  0.24.0). Imports and the build preflight pass; `remesh=none` never calls
  gpytoolbox's numerical paths. The clean set (`scipy==1.17.1`,
  `wcwidth==0.2.14`, no scikit-image pin) is recorded in
  `requirements-sf3d.txt` and needs an image rebuild to apply.
- The SF3D image target needs the ~10 GB PyTorch devel base. This host re-pulled
  it on every attempt (20–55 min each, ~4 MB/s); a third rebuild was abandoned
  because the pull dominated the session. The tagged image is the verified one.
- SF3D `remesh=none` is the intended 12 GB path; `triangle`/`quad` are validated
  settings but unverified, and depend on the `gpytoolbox 0.3.8` /
  `pynanoinstantmeshes` pins.
- Hunyuan3D is blocked (licence excludes the EU/UK/South Korea; ~10 GB shape
  VRAM on a 12 GB card; PyTorch 2.5.1/CUDA 12.4 conflict). No adapter is
  installed.
- The benchmark uses one GPU and a four-image object corpus; results are not a
  general quality claim. Visual quality was inspected only for the live car
  asset in the browser viewer; that is not a general quality claim either. SF3D
  output is lighter (14 774 vertices / 22 818 faces mean) than TripoSR
  (51 246 / 102 298) and carries PBR textures instead of vertex colours.
- Host GPU contention (other desktop applications holding 5–7 GB) caused one
  transient CUDA allocator OOM during a first benchmark attempt; the measured
  run succeeded after the default object worker was stopped. This is a host
  condition, not a pipeline defect.

## 7. Next step

The next post-MVP addendum is [`docs/additions/14_mesh_texture_enhancement.md`](../additions/14_mesh_texture_enhancement.md)
(Stage 4). It was deliberately not started. Increment-11 thresholds,
increment-12 defaults, Phases 2–10 behaviour, the viewer, result/download
contract, outbox and reconstruction algorithms were not re-opened.

## 8. Real-weight completion (2026-11-26)

### 8.1 Access

| Item | Value |
|---|---|
| Token account | `Krutskyh` (user), token label `AI`, classic read token passed as `HF_TOKEN` |
| Gate | `stabilityai/stable-fast-3d`, `gated: auto`, public metadata |
| Probe | `config.yaml` and `model.safetensors` at revision `f0c9a8ff…` both return **HTTP 200** with the token |
| Storage | `HF_TOKEN` added to the gitignored `.env`; the compose overlay forwards it to `sf3d-model-init` only; it is never logged |

### 8.2 Cache population

`docker compose -f compose.yaml -f compose.gpu.yaml -f compose.sf3d.yaml run --rm
sf3d-model-init` downloaded three files (15 m 39 s) and wrote the manifest:

| File | Bytes | SHA-256 |
|---|---|---|
| `config.yaml` | 2 405 | `5e880cfec3dec28d4e20afe07bfa1799c8a561f56f0532ebf1b4022ae4ddc8e4` |
| `model.safetensors` | 4 024 289 892 | `a3416e1cf654e7d4f5e75f116cec2c3f0a14501a77d30c2f6068bbda178de388` |

The manifest keeps `model_id`, the pinned revision and both digests, and now also
records the auxiliary caches (`facebook/dinov2-large` snapshot
`47b73eef…`, open_clip `ViT-B-32`/`laion2b_s34b_b79k`). `verify_weights()` accepts
the extended manifest unchanged.

### 8.3 Defects found by the real run and fixed

1. **The documented real-test command imported MOGEN's own `sf3d` package.** The
   package is named `sf3d`, and `pytest` puts the object-generation directory on
   `sys.path` (the module's `pythonpath = ["."]` setting), so
   `from sf3d.system import SF3D` resolved `object_generation/sf3d/__init__.py`
   and failed with `ImportError: attempted relative import beyond top-level
   package`. The upstream checkout is a namespace package (no `__init__.py`), so
   path order alone cannot win. `loader.import_sf3d_system()` now registers
   `/opt/sf3d-src/sf3d` under `sf3d` explicitly (after dropping only MOGEN's own
   shadowing module) before importing `SF3D`; `SF3D_SOURCE_ROOT` overrides the
   path for other layouts.
2. **The offline worker was missing the auxiliary weights SF3D loads.** A
   populated gated checkpoint is not sufficient: the model instantiates
   `facebook/dinov2-large` and open_clip `ViT-B-32`/`laion2b_s34b_b79k` through
   `transformers`/`open_clip`, and with `HF_HUB_OFFLINE=1` the first task failed
   with `LocalEntryNotFoundError`. `sf3d/download_models.py` now seeds both
   caches (retrying `local_files_only` when the host is offline) and records them
   in the manifest; the caches were populated and the real test then loaded
   offline.
3. **The image's `texture_baker` wheel had no CUDA kernel.** Upstream
   `setup.py` defaults `USE_CUDA` to `torch.cuda.is_available()`, which is false
   in the GPU-less builder, so the extension registered only the CPU kernel and
   every textured task failed at bake time with
   `NotImplementedError: Could not run 'texture_baker_cpp::rasterize' with
   arguments from the 'CUDA' backend`. `ml/object_generation/Dockerfile` now
   passes `USE_CUDA=1` to the wheel build. Because the canonical rebuild needs
   the ~10 GB PyTorch devel layer, the fix was proven in a derived image
   (`.proof/increment13/sf3d-cuda-baker.Dockerfile`, `FROM
   mogen-object-worker:sf3d` plus `cuda-nvcc-12-6`/`cudart`/`cusparse`/`cublas`/
   `cusolver`/`cufft` headers) tagged `mogen-object-worker:sf3d-cuda`; the CUDA
   dispatch table then lists `CUDA: registered at …baker_kernel.cu:300` and a
   real CUDA rasterization returns a `cuda:0` tensor. The canonical SF3D image
   has not been rebuilt yet — the derived image is interim evidence, not a
   canonical build claim.

### 8.4 Verification executed

| Check | Result |
|---|---|
| Real SF3D tests (`RUN_SF3D_REAL_TESTS=1 -m real_sf3d`, offline) | **2 passed** (textured GLB export; two sequential tasks with model reuse and equal `load_seconds`) |
| First real inference | 11 798 vertices / 21 516 faces, 1024 px texture, UVs and normal map, inference 8.91 s, peak CUDA **5 437 214 720 B allocated / 6 635 388 928 B reserved**, cold load 178.9 s (includes DINOv2/CLIP initialisation) |
| Live task through the API (`.proof/increment13/verify-live.ps1 -Mode sf3d`) | **COMPLETED** (project `fe0d8371-0b83-492a-9001-1d567d0a4951`, task `d95ff5c0-50e7-45a2-b72d-1212faef979b`): 664 464-byte GLB, SHA-256 `a3b8fe68c0565aa56ba331c91d5817613887a6fde0de6f529900e438c353b4f5`, device `cuda:0`, inference 2.648 s, 11 808 vertices / 21 516 faces / 2 textures, peak 5.44 GB allocated / 6.64 GB reserved, PBR material normalization |
| Khronos glTF Validator (live GLB) | **0 errors**, 1 warning (`MESH_PRIMITIVE_GENERATED_TANGENT_SPACE`; the normal-mapped material has no `TANGENT` attribute, viewers compute it), 3 hints (`BUFFER_VIEW_TARGET_MISSING`) |
| Real browser (installed Edge, app viewer) | Model loaded in **1.19 s**; viewer facts `textures=2`, `textured=true`, 11 808 vertices / 21 516 triangles; panel shows "Модель содержит встроенные текстуры"; rotate/zoom screenshots captured |
| Worker startup | `sf3d_model_loaded` and `object_generation_pipeline_ready` in the SF3D worker logs |
| Benchmark (4 images, 1 warm-up + 3 repetitions, `cuda:0`) | TripoSR **12/12**, median 7.595 s, p95 7.818 s, mean 2 048 538 B, 51 246 vertices / 102 298 faces, 0 textured, peak 4.45 GB. SF3D **12/12**, median **2.714 s**, p95 3.238 s, mean 772 396 B, 14 774 vertices / 22 818 faces, **12/12 textured**, peak **5.48 GB** |
| Object ML suite (CPU, edited source) | **135 passed, 3 skipped** |
| Default stack restored | object worker recreated as TripoSR (`mogen-object-worker:dev`), `triposr_model_loaded` + `object_generation_pipeline_ready`, healthy; a live TripoSR task completed (`e71acc0f-…`, 1 985 656-byte vertex-colour GLB, 38 168 vertices, peak 4.44 GB); `migration`/`model-init` `Exited (0)`; SF3D cache and derived image retained |

Evidence paths: `.proof/increment13/real-sf3d-test.log`,
`.proof/increment13/live/sf3d-20261126-234604/`,
`.proof/increment13/benchmark/sf3d-benchmark.json`,
`.proof/viewer/object-summary.json`, `.proof/viewer/object-*.png`,
`.proof/increment13/sf3d-cuda-baker-build.log`.

### 8.5 Caveats

- The browser proof script's **extended** steps (camera reset, light/dark
  background, fullscreen, download) fail on this host because its Russian
  `getByRole` labels were saved in a cp1251-mangled form; the model load, viewer
  facts, panel text, rotate and zoom did run. That is a defect in the evidence
  script (`.proof/viewer-tools/proof-viewer.mjs`), not in the asset or viewer.
- SF3D is still opt-in. The default generator remains TripoSR and the default
  compose stack is unchanged; the SF3D worker was run only for this evidence and
  then replaced.
- The SF3D output is lighter and faster than TripoSR on this corpus but visibly
  softer; the benchmark is a throughput/latency measurement, not a quality
  ranking.
- The token was supplied in the session transcript; rotate it in Hugging Face if
  that transcript is retained anywhere beyond this host.
