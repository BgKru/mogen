# Increment 14 close-out review — mesh and texture enhancement

**Date:** 2026-11-26
**Specification:** [`docs/additions/14_mesh_texture_enhancement.md`](../additions/14_mesh_texture_enhancement.md)
**Plan and acceptance criteria:** [`docs/additions/14_implementation_plan.md`](../additions/14_implementation_plan.md)
**Scope:** one post-MVP increment. Object and scene generation keep their existing
generators, preprocessing, task lifecycle, result contract, viewer and download
path; enhancement is an optional post-generation stage with conservative
defaults. No later increment was started.

## 1. Summary

The increment adds a shared CPU mesh-enhancement package, object enhancement
orchestration (cleanup, normals, guarded simplification, xatlas UV generation,
vertex-colour baking, PBR normalisation, disabled AI texture boundary), scene
post-processing that preserves OpenMVS textures/transforms, extended independent
GLB validators, validated worker settings and env examples, compact metadata,
checkpoint invalidation, unit/integration tests, a reproducible benchmark and a
real live object and scene task.

Verified after the change:

| Check | Result |
|---|---|
| Backend suite | **573 passed, 0 failed** (552 baseline + 21 new settings cases) |
| Object ML suite | **135 passed, 3 skipped** (138 collected) |
| Scene ML suite | **136 passed, 2 skipped** (138 collected) |
| Image-quality suite | **47 passed** |
| Frontend suite | **173 passed** (unchanged by increment 14) |
| Real TripoSR inference | **1 passed** with the increment-14 pipeline |
| Khronos glTF Validator | **0 errors, 0 warnings** on the baked object and enhanced scene fixtures (4/3 non-blocking hints) |
| Three.js viewer proof | baked object 59 760 verts / 76 313 tris / 1 material / 1 texture / UV + NORMAL; enhanced scene 16 486 verts / 28 832 tris / 1 texture / UV + NORMAL |
| Live object task | **COMPLETED**: 1 985 656-byte GLB, `enhancement.operations = [mesh_cleanup, normal_correction]`, `NORMAL` present |
| Live scene task (post-process enabled) | **COMPLETED**: 1 630 672-byte GLB, 16 848 verts / 29 323 faces, normals + embedded texture/UV/PBR preserved |
| Ruff / format | clean in both worker images and the backend for changed code |
| `pip check` | clean in both worker images |
| `alembic check` | no schema drift |
| Compose validation | development, GPU, production and SF3D overlays all `config -q` |

**Baseline correction.** The increment-13 handoff and close-out said "scene ML
119 passed + 2 skipped". The JUnit report proves the suite collects 119 cases
including the 2 skips, i.e. **117 passed + 2 skipped**. The current baseline text
in `HANDOFF.md` and `NEXT_SESSION.md` is corrected to 117; the historical
increment-12/13 evidence rows are annotated rather than rewritten.

**Defect found and fixed during verification.** The first live object task
reported `ENHANCEMENT_RESOURCE_EXHAUSTED` because the initial 4 096 MB soft
budget was compared with process peak RSS, which includes the resident TripoSR
model (~4.4 GB). The default was raised to 8 192 MB (still a soft, deployment-
derived budget), the worker was recreated and the live task then completed with
the real cleanup/normal pass.

## 2. Compatibility findings

| Item | Value | Consequence |
|---|---|---|
| Object runtime | Python 3.12.3, torch 2.14.1+cu126, trimesh 4.12.2, numpy 2.3.5, xatlas 0.0.9, Pillow 13.0.0 | no new dependency; xatlas was already pinned |
| Scene runtime | Python 3.12 venv, trimesh 4.12.2, numpy 2.3.5, Pillow 13.0.0, **no SciPy** | scene UV/AI enhancement stays disabled; normals use an area-weighted NumPy path rather than trimesh's dense SciPy fallback |
| Quadric simplifier | `fast_simplification`, `pymeshlab`, `open3d` absent | production simplification safely skips with `SIMPLIFIER_UNAVAILABLE`; the attribute/deviation guard is tested with an injected simplifier |
| xatlas cost | 76 313-face TripoSR mesh | 39 s for the unwrap at 512 px; the vectorised bake itself is <1 s |
| Legacy export | trimesh writes `COLOR_0` without `NORMAL` by default; `include_normals=True` adds it | unchanged legacy shape when enhancement does not establish normals |
| Real assets | retained TripoSR GLB (38 241 verts / 76 315 faces) and 16 486-vertex OpenMVS scene | used for benchmark and GLB integration; unit tests use in-repo fixtures |

## 3. Implemented

**New files:** `ml/mesh_enhancement/{__init__,metrics,cleanup,normals,simplification,manifest}.py`,
`ml/object_generation/{enhancement,texture_baking,texture_generation}.py`,
`ml/object_generation/benchmarks/run_enhancement_benchmark.py`,
`ml/scene_reconstruction/{enhancement,benchmark_enhancement}.py`,
the new test modules, `docs/additions/14_implementation_plan.md` and this review.

**Modified:** both `config.py` files, object `pipeline.py`/`exporter.py`/`validator.py`/`exceptions.py`,
scene `pipeline.py`/`exporter.py`/`validator.py`/`diagnostics.py`/`exceptions.py`,
`backend/app/core/config.py`, both Dockerfiles, `compose.yaml`, `.dockerignore`,
`.env.example`, `.env.production.example`, `docs/specifications/06_object_generation.md`,
`docs/specifications/07_scene_reconstruction.md`, both ML READMEs, `HANDOFF.md`
and `NEXT_SESSION.md`.

**Behaviour:**

- Object enhancement runs between the normalized generator mesh and export,
  inside `MODEL_GENERATION`; persisted stage identifiers are unchanged.
- Default object policy is conservative cleanup + normal validation. Cleanup
  removes repeated-index/zero-area faces and unreferenced vertices, merges
  duplicates only within a bbox-diagonal-relative tolerance and never across UV
  seams; it does not fill holes or smooth.
- Normals are area-weighted and finite; winding correction is limited to a
  watertight single component. Exported `NORMAL` is re-read by the validator.
- Simplification is target/deviation guarded and attribute-checked; the
  production image reports a safe skip because no quadric simplifier is pinned.
- xatlas UV generation remaps positions, colours and faces; existing valid UVs
  are preserved unless baking needs a new atlas.
- Vertex-colour baking creates an embedded base-colour texture with a PBR
  metallic-roughness material (`metallicFactor=0`, `roughnessFactor=0.9`); a
  generator-provided texture is preserved rather than rebaked. A 76k-face mesh
  bakes at 512 px in ~38 s, of which ~39 s is xatlas and <1 s rasterisation.
- Scene post-processing is off by default. When enabled it mutates geometry in
  place, preserving nodes/transforms/materials/textures; textured geometry is
  never unwrapped, merged or simplified. `RefineMesh`/`TextureMesh` are not
  repeated, and scene UV/AI generation is rejected by configuration.
- AI texture generation is a protocol + lazy factory + output validator with a
  disabled backend. No model is a runtime dependency; enabling it fails
  validation with a clear reason.
- `run.json` and result metadata gain a compact `enhancement` block (operations,
  before/after metrics, flags, skips, fallback, timings, peak RSS, manifest with
  dependency versions and source fingerprint). No paths, tensors or image
  buffers are exposed.
- Scene export reuse is guarded by `enhancement_manifest.json`; changed settings,
  dependencies or source fingerprint force a fresh repack.

## 4. Task evidence

| Task | Evidence |
|---|---|
| I14-01 Compatibility/design/acceptance criteria | Plan Sections 2–3; runtime probes for trimesh/xatlas/Pillow/normals; simplifier absence recorded |
| I14-02 Shared metrics/cleanup/normals/simplification/manifest | `ml/mesh_enhancement/`; `test_enhancement.py` cleanup/normal/simplify/manifest cases; both worker suites import it |
| I14-03 Object enhancement config/orchestration/fallback/memory | `enhancement.py`; fallback on/off, memory-budget, cancellation and manifest tests; live object metadata |
| I14-04 xatlas UV/bake/PBR | `texture_baking.py`; UV remap, bake/export/reopen, PBR clamp/default and atlas-average tests; Khronos 0/0 and Edge viewer facts |
| I14-05 AI texture boundary | `texture_generation.py`; disabled/factory/output-validation tests; backend rejection tests |
| I14-06 Object pipeline/export integration | `pipeline.py`/`exporter.py`; default and baked pipeline tests; live object task with NORMAL |
| I14-07 Object validator extension | `validator.py`; NORMAL/UV/PBR/external-image/corrupt-image tests; legacy asset test |
| I14-08 Scene enhancement/config/checkpoint | `scene_reconstruction/enhancement.py`, `pipeline.py`, `exporter.py`; preservation/simplification-skip/fingerprint/cache tests; live scene task |
| I14-09 Scene validator extension | `validator.py`; NORMAL/PBR factor/texture-integrity/warning tests; legacy scene test |
| I14-10 Backend settings/env/Dockerfiles | `backend/app/core/config.py`; 21 settings tests; mapping tests in both ML suites; Compose `config -q`; Dockerfile shared-package copies (canonical build limitation in Section 6.3) |
| I14-11 Unit/integration tests | 135 object + 136 scene + 573 backend + 47 image-quality + 173 frontend passed |
| I14-12 Benchmark/live/docs/close-out | benchmark JSON in `.proof/increment14/benchmark/`; live summaries in `.proof/increment14/live/`; this review, HANDOFF, NEXT_SESSION, READMEs and spec updates |

## 5. Requirement traceability

| ID | Result | Evidence |
|---|---|---|
| I14-AC-01 | Passed | Existing object/scene suites green; live object and scene tasks completed; legacy vertex-colour GLB still validates and loads |
| I14-AC-02 | Passed | Cleanup/normal unit tests; `before`/`after` component/degenerate/non-manifold/duplicate metrics in metadata; live `mesh_cleanup` + `normal_correction` |
| I14-AC-03 | Passed (guard) / safe skip (production) | Injected simplifier accepts within deviation, rejects excessive deviation and missing attributes; default image records `SIMPLIFIER_UNAVAILABLE` and keeps the source; no unverified simplifier pinned |
| I14-AC-04 | Passed | xatlas remap tests on coloured/multi-seam meshes; finite UV/range checks; live baked object has 59 760 verts / UV + NORMAL |
| I14-AC-05 | Passed | Bake/export/reopen test; Khronos 0/0; benchmark and Edge viewer load on the baked fixture. A second live *baking* task was not run; the live object task used the default cleanup+normals policy, and this limitation is stated |
| I14-AC-06 | Passed | Scene enhancement preserves material/texture/object identity and transforms; live scene result has 1 embedded texture, UVs and PBR, no repeated OpenMVS stage |
| I14-AC-07 | Passed | PBR factor/reference/colour-space tests; validator rejects out-of-range factors, missing UVs and external/corrupt images |
| I14-AC-08 | Passed | Disabled backend/factory/output-validation tests; enabling AI texture fails settings validation; no model dependency added |
| I14-AC-09 | Passed | Memory-budget, cancellation, fallback on/off, manifest invalidation and error-code tests; live memory-budget defect found and fixed |
| I14-AC-10 | Passed | Reproducible object and scene benchmarks recorded in `.proof/increment14/benchmark/`; times/counts below |
| I14-AC-11 | Passed | No route/schema/viewer/DB/stage change; backend suite green; metadata contains no paths/tensors |
| I14-AC-12 | Passed | Legacy vertex-colour GLB, baked textured object and multi-mesh scene round-trips; Khronos 0/0; Three.js/Edge viewer proof |
| I14-AC-13 | Passed | Extended object and scene validators: NORMAL shape/finite/non-zero, UV finite/range, PBR factors/slots, embedded image integrity; legacy assets still pass |
| I14-AC-14 | Passed | 21 backend settings cases, object/scene mapping tests, env examples, Compose validation; API image imports no ML package |

## 6. Verification executed

Baseline before any change (2026-11-26):

| Check | Result |
|---|---|
| Development stack | nine services healthy; `migration`/`model-init` `Exited (0)`; workers answer `celery inspect ping` |
| Object ML | **76 passed, 3 skipped** (79 collected) |
| Scene ML | **117 passed, 2 skipped** (119 collected; docs over-counted by 2) |
| Backend | **552 passed** |
| Image-quality | **47 passed** |
| SF3D gated access | **blocked**: `stabilityai/stable-fast-3d` `config.yaml` returned **403** for the available token; no real SF3D check was possible |

After the change (canonical suites in the worker images used for verification):

```text
docker run --rm mogen-object-worker:dev python -m pytest /opt/object_generation/tests -q
  -> 135 passed, 3 skipped (138 collected)
docker run --rm mogen-scene-worker:dev /opt/venv/bin/python -m pytest /opt/scene_reconstruction/tests -q
  -> 136 passed, 2 skipped (138 collected)
docker run --rm mogen-scene-worker:dev /opt/venv/bin/python -m pytest /opt/image_quality/tests -q
  -> 47 passed
docker compose run --rm --no-deps api pytest -q
  -> 573 passed
docker run --rm mogen-frontend:dev npm run test:run
  -> 173 passed
```

Additional checks: Ruff/format clean in both worker images and the backend for
changed files; `pip check` clean in both worker images; `alembic check` no drift;
all Compose overlays `config -q`; real TripoSR opt-in test 1 passed.

### 6.1 Live tasks

Both tasks were created through the public API (registration, project, image
upload, generation, status polling, result and download) on a unique throw-away
user; identifiers are in `.proof/increment14/live/*-summary.json`.

| Task | Result |
|---|---|
| OBJECT (default policy, CPU/GPU worker) | **COMPLETED**; 1 985 656-byte GLB; inference 1.648 s; `generator.name=triposr`; `enhancement.operations=[mesh_cleanup, normal_correction]`; 38 168 verts / 76 313 faces; `NORMAL` present; no paths/tensors |
| SCENE (post-process enabled for the drill) | **COMPLETED**; 1 630 672-byte GLB; 16 848 verts / 29 323 faces; `scene_mesh_cleanup` + `scene_normal_correction`; 1 embedded texture, UVs and PBR preserved; `normal_export=true`; 0 validator warnings |

The scene worker was restored to the default `SCENE_MESH_POSTPROCESS_ENABLED=false`
after the drill.

### 6.2 Benchmarks

Real retained assets, three object repetitions and two scene repetitions:

| Scope | Variant | Median | Output |
|---|---|---:|---|
| Object | baseline | 0.639 s | 1 528 744 B, 38 241/76 315 |
| Object | cleanup+normals | 0.825 s | 1 985 656 B, 38 168/76 313, NORMAL |
| Object | baked 512 px | 38.087 s | 3 214 808 B, 59 760/76 313, texture+NORMAL |
| Scene | baseline | 0.204 s | 940 728 B |
| Scene | cleanup+normals | 1.229 s | 1 138 776 B, texture+UV+NORMAL |
| Scene | simplification attempt | 1.157 s | textured geometry safely skipped, unchanged geometry |

Object baking is opt-in; xatlas unwrap dominates its cost (39 s on 76 313
faces), not the rasteriser. Scene post-processing is likewise opt-in. Quality is
reported through mesh/appearance facts and the Khronos/Three.js checks, not a
single proxy metric.

### 6.3 Image rebuild status

The canonical `ml/object_generation/Dockerfile` build was **not completed**: it
needs the ~6.4 GB `pytorch:...-devel` layer, and this host pulled it at
<0.3 MB/s. The canonical scene rebuild was also stopped after it began
recompiling OpenCV/OpenMVS. To verify the runtime rather than wait for hours, a
derived image was built from each already-verified runtime base
(`FROM mogen-object-worker:dev` / `FROM mogen-scene-worker:dev`) with the changed
`ml/` and `backend/app` sources copied in; those are the images used for the
suites, the live tasks and `pip check`. The Dockerfiles themselves add the same
`ml/mesh_enhancement` copy and remain the canonical build definition; the
missing full-build verification is recorded here as a limitation, not claimed
as passed.

## 7. Known limitations

- Simplification is implemented and guarded but has no pinned quadric backend;
  the production image records `SIMPLIFIER_UNAVAILABLE` and retains the source.
- Scene UV regeneration and scene AI texture generation are intentionally
  rejected; OpenMVS keeps ownership of photogrammetric UV/atlas work.
- AI texture generation is a disabled interface; no model passed the licence,
  compatibility, cache and RTX 3060 review.
- The object bake path is measured on the retained real TripoSR GLB but was not
  run as a second live task; the fixture export, Khronos validator and Edge
  viewer load are the end-to-end evidence.
- Scene normal correction sets an explicit NORMAL only when post-processing is
  enabled; the default scene path remains the previous material/texture-only
  output.
- The canonical image rebuild is blocked on the slow devel-layer pull/deep
  recompile described in Section 6.3; runtime verification used derived images.
- The retained real assets and the browser screenshots live in `.proof/`
  (gitignored); the benchmark JSON is reproducible with the documented command.
- SF3D real-weight verification remains blocked on gated Hugging Face access
  (rechecked 2026-11-26: `config.yaml` returned 403 for the available token);
  nothing in increment 14 claims it.

## 8. Next step

The next post-MVP addendum is
[`docs/additions/15_neural_scene_reconstruction.md`](../additions/15_neural_scene_reconstruction.md).
It was deliberately not started. Increment-11 thresholds, increment-12 feature
matching, Phases 2–10 behaviour, the viewer, result/download contract, outbox and
reconstruction algorithms were not re-opened.
