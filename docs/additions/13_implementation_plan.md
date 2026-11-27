# Increment 13 — Implementation Plan and Acceptance Criteria

**Specification:** [`13_advanced_object_generation.md`](13_advanced_object_generation.md)
**Scope:** Optional Stable Fast 3D generator for single-image object generation;
TripoSR stays the default, unchanged baseline. Hunyuan3D is gated and documented
as blocked.
**Status:** Implemented (2026-11-25). Real SF3D weight/inference/live-task/
benchmark verification is blocked on gated Hugging Face access; evidence in
[`../reviews/increment13_closeout.md`](../reviews/increment13_closeout.md).
**Date:** 2026-11-25.

## 1. Scope resolution

The addendum ends with "Do not start Stage 4 work. Stop after delivering the
implementation report and wait for approval." "Stage 4" is the later
`14_mesh_texture_enhancement.md` increment, so it does not restrict this
increment. The direct session instruction is to implement increment 13 only.
No Stage 4 mesh/texture enhancement is implemented here.

The addendum also says to implement Hunyuan3D "only after a separate
license/territory review and hardware feasibility check … if these checks cannot
be satisfied, document the adapter as blocked rather than bypassing the gate."
Section 4 records the review result: Hunyuan3D is **blocked** and is not
installed. Its configuration surface still validates and refuses to initialize.

## 2. Compatibility findings (2026-11-25)

| Component | Value | Notes |
|---|---|---|
| SF3D source | commit `ff21fc491b4dc5314bf6734c7c0dabd86b5f5bb2` (2025-01-22) | official Stability-AI repository; ships `sf3d/`, `texture_baker/`, `uv_unwrapper/` |
| SF3D weights | `stabilityai/stable-fast-3d` revision `f0c9a8ffd62cb1bbc8a7a53c9f87a0be1b6be778` | `config.yaml` + `model.safetensors` (3.84 GB) |
| SF3D licence | Stability AI Community License (gated HF repo) | review required before distribution/hosted use; attribution preserved |
| Worker runtime | Python 3.12.3, torch 2.14.1+cu126, CUDA 12.6, RTX 3060 12 GB | existing TripoSR image |
| Native extensions | `texture_baker` (CUDAExtension), `uv_unwrapper` (CppExtension) | require `nvcc` at build time; only the devel base image has it |
| Dependency conflicts | upstream pins `numpy==1.26.4`, `transformers==4.42.3`, `trimesh==4.4.1`, `huggingface-hub==0.23.4`, `rembg==2.0.57` | conflict with the TripoSR image (`numpy 2.3.5`, `transformers 4.46.3`, `trimesh 4.12.2`, `hub 0.26.2`, `rembg 2.0.87`) |
| gpytoolbox | upstream `0.2.0` has no CPython 3.12 wheel | pin `0.3.8` (cp312 wheel); only the optional remesh paths call its API, and the default `remesh=none` never does |

Isolation decision: the SF3D dependency set is installed into a dedicated
`--target` directory (`/opt/sf3d-site`) inside a separate **`sf3d` build stage**
and injected before site-packages with `PYTHONPATH` for the SF3D worker only.
The TripoSR runtime and its site-packages stay byte-identical. The compiled
extensions are built in a devel-based stage and copied as wheels.

Hunyuan3D review: the published Hunyuan3D-2.1 licence excludes the European
Union, the United Kingdom and South Korea, the shape stage is reported at
~10 GB VRAM (texture ~21 GB, both ~29 GB), and its documented PyTorch 2.5.1 /
CUDA 12.4 stack conflicts with the pinned 2.14.1 / 12.6 runtime. On the 12 GB
target the adapter cannot be integrated without violating the licence gate or
the dependency isolation rule, so it is **blocked** (Section 8).

## 3. Design decisions

1. **Contract.** `generator_base.py` defines an `ObjectGenerator` protocol
   (`name`, `revision`, `model_id`, `model_revision`, `capabilities()`,
   `load()`, `generate()`, `unload()`), a `GeneratorResult` carrying the mesh,
   UV/material/texture availability, timing, peak CUDA bytes and JSON-safe
   diagnostics, and a `PreparedImage` dataclass that wraps the existing
   preprocessing result plus the RGBA variant SF3D needs. Adapters never touch
   storage, the database, Celery progress or cancellation.
2. **Factory and allowlist.** `generator_factory.py` maps the configured name to
   an adapter: `triposr` and `sf3d` are implemented; `hunyuan3d` is rejected
   with a stable code because the adapter is blocked. Unknown names are rejected
   during settings validation, so the worker never starts with a bad policy.
3. **TripoSR stays the default and the regression baseline.** The existing
   `TripoSRGenerator` inference, preprocessing, mesh validation and vertex-colour
   export are reused unchanged through a thin adapter. No new model download
   happens for `OBJECT_GENERATOR=triposr`; the existing cache/manifest path is
   untouched.
4. **One generator per worker process.** Selection happens at worker bootstrap;
   the model is loaded once and never swapped per task. `OBJECT_GENERATOR_FALLBACK`
   permits a *pre-inference* fallback to TripoSR only; after inference starts a
   failure is a stable task error. The fallback reason and actual generator are
   recorded.
5. **SF3D preprocessing.** The shared decode, one background removal and one
   foreground crop/pad/ratio pass produce an RGBA image; the adapter passes that
   image to `SF3D.run_image`, which only resizes it to the model's conditioning
   size. Upstream `rembg`/`resize_foreground` are never called, so background
   removal and foreground resizing execute exactly once.
6. **Output normalization and export.** `normalization.py` validates the
   generator output (finite vertices, valid faces, UVs when a texture is
   present, embedded image, no external paths) and returns a mesh accepted by
   the exporter. `export_glb` keeps the TripoSR vertex-colour path unchanged and
   gains a textured path that preserves UVs, the base-colour texture and
   material parameters. The final validator accepts a GLB with either `COLOR_0`
   or a `TEXCOORD_0` + `baseColorTexture` pair whose image is embedded; a GLB
   with neither is still rejected (`OBJ-AC-10` is preserved for TripoSR).
7. **Metadata.** `run.json` and result metadata gain a `generator` object
   (`name`, source `revision`, `model_id`, `model_revision`, `device`,
   `preprocessing_profile`, timings, peak CUDA allocated/reserved bytes when
   measured, SF3D texture/remesh settings). Unavailable metrics are omitted, not
   zero-filled. Existing keys are preserved; no paths, tokens or tracebacks.
8. **Configuration.** New validated `OBJECT_GENERATOR*` and `OBJECT_SF3D_*`,
   `OBJECT_HUNYUAN3D_*` settings; SF3D requires an explicit enable flag, a
   pinned model revision and a checksum manifest. Model caches are separate
   (`/models/sf3d`), populated before worker startup, and the worker stays
   offline at task time.
9. **Deployment.** A `compose.sf3d.yaml` overlay switches the existing single
   `object-worker` service to the SF3D image target and settings, so one
   unambiguous generator policy owns the `object_generation` queue. The default
   stack is untouched.
10. **Hunyuan3D gate.** `OBJECT_HUNYUAN3D_ENABLED=false` by default; enabling it
    also requires an explicit licence acknowledgement and a territory that is
    not in the documented excluded set, and `OBJECT_HUNYUAN3D_MODE` must be
    `shape`. Even then the factory reports `GENERATOR_NOT_AVAILABLE` because the
    adapter is not installed. Texture generation is rejected for this profile.

## 4. Implementation tasks

| ID | Task | Files |
|---|---|---|
| I13-01 | Compatibility, licence and dependency study; isolation decision | this plan |
| I13-02 | Generator contract, normalised result types, capabilities | `ml/object_generation/generator_base.py` |
| I13-03 | Factory + allowlist + startup rejection | `ml/object_generation/generator_factory.py` |
| I13-04 | TripoSR adapter and pipeline dispatch; stages unchanged | `generator.py`, `pipeline.py` |
| I13-05 | SF3D loader (manifest/offline), adapter (run_image), preprocessing | `sf3d/` |
| I13-06 | Normalisation, textured GLB export, validator extension | `normalization.py`, `exporter.py`, `validator.py`, `mesh_processor.py` |
| I13-07 | Metadata + redaction; error codes and fallback | `pipeline.py`, `exceptions.py` |
| I13-08 | Backend settings, validation, bootstrap, env examples | `backend/app/core/config.py`, `backend/app/tasks/object_pipeline.py`, `.env.example`, `.env.production.example` |
| I13-09 | SF3D image target, model-init service, Compose overlay | `ml/object_generation/Dockerfile.sf3d`, `compose.sf3d.yaml` |
| I13-10 | Unit tests, textured fixtures, opt-in real test, benchmark runner | `ml/object_generation/tests/`, `benchmarks/` |
| I13-11 | Real SF3D run on the RTX 3060: load, infer, export, validate, viewer load, two sequential tasks, failure isolation | evidence under `.proof/increment13/` |
| I13-12 | Benchmark TripoSR vs SF3D on identical images; docs and close-out review | `docs/reviews/increment13_closeout.md`, README, HANDOFF, NEXT_SESSION |

## 5. Acceptance criteria

The addendum lists unnumbered bullets (Section 11); the IDs below are
plan-local and map one-to-one.

| ID | Criterion | Verification |
|---|---|---|
| I13-AC-01 | Existing TripoSR behaviour, output and tests remain compatible | object suite before/after; vertex-colour export test; command/stage equality |
| I13-AC-02 | `OBJECT_GENERATOR=triposr` is the default and needs no new downloads | settings default test; worker starts with the existing cache |
| I13-AC-03 | SF3D selectable through validated config and produces a valid textured GLB | unit pipeline test with a fake SF3D model + opt-in real inference |
| I13-AC-04 | SF3D UVs/materials/textures survive normalisation, export and Three.js load | textured GLB fixture assertions + real viewer load |
| I13-AC-05 | Generator identity, pinned revisions, timings and available VRAM metrics recorded | metadata assertions; live result metadata inspection |
| I13-AC-06 | Model caches are separate, checksum-verified and populated before startup; no download at task time | manifest tests; offline task; `HF_HUB_OFFLINE=1` |
| I13-AC-07 | GPU-heavy inference is serialised for the 12 GB profile | concurrency 1; one model resident; measured peak VRAM |
| I13-AC-08 | Hunyuan3D disabled by default and cannot initialise when the licence gate fails | settings validation + factory tests with deterministic fixtures |
| I13-AC-09 | Hunyuan3D shape-only integration isolated from the TripoSR runtime | **blocked** — adapter not installed (licence/VRAM/dependency review) |
| I13-AC-10 | Hunyuan3D texture generation disabled for the 12 GB profile | `shape_texture` rejected by settings validation |
| I13-AC-11 | Celery lifecycle, progress stages, cancellation, storage and GLB validation intact | existing backend tests + live task |
| I13-AC-12 | CPU unit tests pass; real-model and benchmark reports produced for every supported adapter | object suite; real SF3D evidence; benchmark results (TripoSR measured, SF3D measured when weights are accessible) |
| I13-AC-13 | No public API or frontend changes | no route/schema/viewer diff |
| I13-AC-14 | Unknown, disabled or uninstalled generators are rejected during startup | settings/factory rejection tests |
| I13-AC-15 | Preprocessing capabilities prevent duplicate background removal and resizing | RGBA pass-through test with a spy rembg session |
| I13-AC-16 | Failure mapping, cancellation and pre-inference fallback are tested; unsupported output is rejected | exception mapping, cancellation, fallback and normalisation rejection tests |

## 6. Test plan

**CPU unit tests (no weights):** factory defaults and rejections; protocol
conformance; configuration validation (valid and invalid values); preprocessing
capability flags and single background removal; normalisation of vertex-colour,
textured and invalid outputs; textured GLB export and validation; metadata
identity/timing/redaction; fallback and cancellation; Hunyuan3D licence gate.

**Opt-in integration (`RUN_REAL_MODEL_TESTS=1` + SF3D weights):** manifest and
checksum verification, real load, one inference, GLB export, validator,
Three.js load, two sequential tasks, failed-inference isolation.

**Benchmark:** TripoSR vs SF3D on the same three object photographs, one warm-up
plus three repetitions, median/p95 latency, peak VRAM, file size, vertices/faces,
textures, failure rate.

## 7. Risks and mitigations

| Risk | Mitigation |
|---|---|
| SF3D weights are gated (HF licence acceptance) | access confirmed by the operator before the real run; otherwise the real checks are reported **blocked**, never simulated |
| New dependencies conflict with torch 2.14.1 / numpy 2 | isolated `--target` site directory + `PYTHONPATH`; TripoSR env untouched; import matrix tested |
| Native texture-baker/UV-unwrapper builds need CUDA | dedicated devel build stage; wheels copied into the runtime; build-time verification |
| Disk capacity (scene image 20.7 GB, SF3D weights 3.84 GB) | Docker build cache pruned before the build; no unnecessary image rebuilds |
| GPU is shared with the running object worker (~5.6 GB) | stop the TripoSR worker during the SF3D drill, restart afterwards; one model resident |
| Validator change weakens the TripoSR colour rule | textured acceptance requires embedded image + material + `TEXCOORD_0`; TripoSR fixture still asserts `COLOR_0` |

## 8. Blocked item and known limits

- **Hunyuan3D:** blocked. No adapter is installed; the configuration gate rejects
  it with a stable code. Reported as blocked, not as implemented.
- **SF3D remeshing:** `remesh=none` is the verified path; `triangle`/`quad` are
  exposed as validated settings but are not verified in this increment (they add
  CPU time and depend on gpytoolbox/pynanoinstantmeshes versions pinned here).
- **Benchmark scope:** one GPU, one object corpus; results are not a general
  quality claim.
