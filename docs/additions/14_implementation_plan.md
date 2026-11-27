# Increment 14 — Implementation Plan and Acceptance Criteria

**Specification:** [`14_mesh_texture_enhancement.md`](14_mesh_texture_enhancement.md)
**Scope:** one post-MVP increment: optional, conservative mesh/texture
enhancement for object and scene assets. TripoSR/Stable Fast 3D and
COLMAP/OpenMVS remain the source stages; increments 11–13 and Phases 2–10 are
not re-opened.
**Status:** Implemented (2026-11-26). Evidence:
[`../reviews/increment14_closeout.md`](../reviews/increment14_closeout.md).
**Date:** 2026-11-26.

## 1. Scope resolution

The addendum's final line says "Deliverable: `14_mesh_texture_enhancement.md`.
This is a documentation-only task; do not implement code." That line belongs to
the task that authored the addendum. The direct session instruction is to read
the addendum, write this plan and implement **only** increment 14. The
specification's own Sections 2–12 are clearly implementation instructions
("Before editing, inspect…", "Implement object-side CPU cleanup…"), so the
session instruction governs and the trailing line is recorded here as a
documentation artefact rather than silently ignored (guide Section 4.5).

No later increment (for example `15_neural_scene_reconstruction.md`) is started.
No public API, frontend workflow, database schema, persisted task stage, result
contract, viewer, outbox or reconstruction algorithm is changed.

## 2. Compatibility findings (2026-11-26)

| Component | Value | Consequence |
|---|---|---|
| Object worker runtime | Python 3.12.3, torch 2.14.1+cu126, trimesh **4.12.2**, numpy **2.3.5**, xatlas **0.0.9**, scipy 1.18.1, Pillow 13.0.0 | xatlas and trimesh are already pinned; no new object dependency is needed |
| Scene worker runtime | Python 3.12 (`/opt/venv`), trimesh **4.12.2**, numpy **2.3.5**, Pillow 13.0.0 | no texture/UV dependency is added; scene UV regeneration stays disabled |
| Quadric simplifier | `fast_simplification`, `pymeshlab` and `open3d` are **not installed**; trimesh's `simplify_quadric_decimation` therefore raises | simplification orchestration and the deviation/attribute guard are implemented and unit-tested with an injected simplifier; production **safely skips** with a recorded reason. No unverified decoder/remesher is pinned |
| Existing GLB export | trimesh writes `COLOR_0` but no `NORMAL` by default; `include_normals=True` adds valid `NORMAL` for vertex-colour and textured meshes | normals are exported only when the enhancement stage produced/validated them, so the untouched legacy path is byte-compatible |
| Existing GLB fixtures | real TripoSR object GLB and real SPA/OpenMVS scene GLB in `.proof/` | used for the reproducibility benchmark and GLB integration checks; unit tests keep in-repo synthetic fixtures |
| Time zone / clock | tests call stage methods directly; the pipeline clock is initialised in `__init__` (increment 12 fix) | the enhancement code must use the same monotonic clock, never a zero default |

## 3. Design decisions

1. **One small shared package, no framework.** Pure CPU utilities live in
   `ml/mesh_enhancement/`: metrics, conservative cleanup, normal validation,
   simplification guard/manifest. Both worker images install it as
   `mesh_enhancement` under `/opt` (same pattern as the shared
   `image_quality` package). Object-specific orchestration, UV generation and
   baking stay in `ml/object_generation/`; scene-specific orchestration stays in
   `ml/scene_reconstruction/`. Neither worker imports the other's package.
2. **Enhancement is opt-in except conservative object cleanup.** Object
   defaults: cleanup + normal validation on; simplification, UV generation,
   baking and AI texture off. Scene post-processing is off by default. Disabled
   operations return the incoming asset unchanged and are recorded as skipped.
3. **Source geometry is validated first.** `validate_mesh()` semantics are
   unchanged; a non-finite vertex, invalid face index or degenerate bounding box
   is a hard failure with the existing code. Optional-stage failures honour
   `ENHANCEMENT_FALLBACK_TO_ORIGINAL` and continue from the last valid asset.
4. **Cleanup is conservative and deterministic.** Remove repeated-index and
   zero-area faces, unreferenced vertices and small components only when
   explicitly configured; merge duplicate vertices only within a scale-aware
   tolerance (fraction of the bounding-box diagonal) and never when UVs exist
   (a seam must not be collapsed). No hole filling, no watertightness forcing,
   no smoothing (the setting is validated to 0 in this delivery).
5. **Normals are derived, not invented.** Face/vertex normals are recomputed
   when absent or invalid; winding is corrected only for a watertight,
   single-component mesh. Open/non-manifold meshes keep their winding and record
   `winding_skipped`. Exported `NORMAL` data is re-read by the independent GLB
   validator.
6. **Simplification is guarded or skipped.** When enabled and the face budget is
   exceeded, a simplifier must return a mesh with matching attribute counts; a
   sampled surface-distance check rejects candidates above
   `*_MESH_MAX_DEVIATION` (fraction of bbox diagonal). Because no quadric
   simplifier is pinned in the images, the default outcome is a recorded
   `SIMPLIFIER_UNAVAILABLE` skip with the original mesh retained; the guard is
   proven with an injected deterministic simplifier in tests.
7. **UV generation is xatlas and attribute-safe.** `xatlas.parametrize` returns a
   vertex mapping; positions, vertex colours and normals are remapped with it,
   and faces are reindexed. Valid generator/OpenMVS UVs are preserved unless
   regeneration is explicitly requested. UVs are validated for finite values and
   atlas range with a padding tolerance.
8. **Texture baking is deterministic CPU rasterisation.** The baked atlas
   interpolates the existing vertex colours over the xatlas UV layout, fills
   seams with a bounded dilation pass and creates a PBR material whose
   `baseColorTexture` is an in-memory image. It never invents surface detail; a
   textured generator/OpenMVS asset is preserved rather than rebaked. The atlas
   is embedded by the existing exporter.
9. **PBR normalisation is minimal and truthful.** Material factors are clamped
   to glTF ranges and missing factors use dielectric defaults
   (`metallicFactor=0`, `roughnessFactor=0.9`). Base colour stays sRGB and
   normal/metallic-roughness stay linear because they are written through the
   glTF texture slots, not relabelled. No normal/roughness/metallic map is
   synthesised from a base-colour image.
10. **AI texture generation is an interface, not a model.** A backend protocol,
    lazy factory, output validation and disabled backend are implemented.
    `OBJECT_AI_TEXTURE_ENABLED=true` / `SCENE_AI_TEXTURE_ENABLED=true` are
    rejected during configuration because no compliant model has passed the
    licence, compatibility, cache and RTX 3060 review. The specification
    explicitly permits this disabled/unavailable delivery.
11. **Metadata is compact and path-free.** `run.json` and result metadata gain an
    `enhancement` block with operation ids, dependency versions, before/after
    counts and flags, warnings/skips, fallback and timings. No tensors, image
    buffers, prompts, absolute paths or tracebacks are exposed. Persisted stage
    identifiers are unchanged; enhancement runs inside the existing
    generation/export stages.
12. **Checkpoint invalidation.** Object enhancement has no reusable checkpoint,
    but its manifest is written into `run.json`. Scene export reuse is guarded by
    `enhancement_manifest.json`: a settings/dependency/source-fingerprint change
    deletes the cached GLB and forces a fresh repack.

## 4. Implementation tasks

| ID | Task | Files |
|---|---|---|
| I14-01 | Compatibility study, design, acceptance criteria | this plan |
| I14-02 | Shared metrics, conservative cleanup, normals, simplification guard, versions/fingerprint/manifest | `ml/mesh_enhancement/` |
| I14-03 | Object enhancement config + orchestration, fallback, memory budget, metadata | `ml/object_generation/enhancement.py`, `exceptions.py`, `config.py` |
| I14-04 | xatlas UV generation, vertex-colour baking, PBR material normalisation | `ml/object_generation/texture_baking.py` |
| I14-05 | AI texture backend protocol, disabled backend, output validation | `ml/object_generation/texture_generation.py` |
| I14-06 | Object pipeline integration between generator output and GLB export; normals export | `ml/object_generation/pipeline.py`, `exporter.py` |
| I14-07 | Object validator: NORMAL, TEXCOORD finiteness/range, PBR refs, embedded images, quality warnings | `ml/object_generation/validator.py` |
| I14-08 | Scene conservative enhancement, config, checkpoint manifest; no repeated OpenMVS stages | `ml/scene_reconstruction/enhancement.py`, `config.py`, `pipeline.py`, `exporter.py`, `diagnostics.py` |
| I14-09 | Scene validator: normals/UV/material/PBR/texture integrity, multi-mesh compatibility | `ml/scene_reconstruction/validator.py` |
| I14-10 | Backend settings + validation + worker mapping; env examples; both Dockerfiles install the shared package | `backend/app/core/config.py`, `ml/*/config.py`, `.env.example`, `.env.production.example`, Dockerfiles |
| I14-11 | Unit/integration tests: cleanup, normals, simplification, UV, baking, PBR, fallback, cancellation, manifest, GLB round-trip | both `tests/` trees, `backend/tests/unit/` |
| I14-12 | Reproducible benchmark + live task evidence + documentation + close-out | `benchmarks/`, `docs/` |

## 5. Acceptance criteria

| ID | Criterion | Verification |
|---|---|---|
| I14-AC-01 | Existing object and scene generation continues to work with enhancement disabled/default settings; existing TripoSR vertex-colour and OpenMVS textured GLBs stay valid and load. | Existing suites re-run; legacy GLB round-trip; live task |
| I14-AC-02 | Conservative cleanup and normal correction are implemented with measurable before/after diagnostics. | Unit tests + `enhancement.before/after` metadata |
| I14-AC-03 | Optional simplification is guarded by a geometry-deviation limit and preserves required attributes/materials or safely skips. | Injected simplifier tests (accept/reject/attribute mismatch); documented unavailable skip |
| I14-AC-04 | xatlas UV generation works for object meshes and preserves/remaps positions, colours, normals and faces correctly. | Unit tests on coloured/multi-component meshes + UV validation |
| I14-AC-05 | Object texture baking produces a self-contained GLB with valid UVs/material references; the old `object_bake_texture=true` rejection is removed only now. | Bake/export/reopen/Khronos validation; validator metadata; backend settings test |
| I14-AC-06 | OpenMVS scene UVs/textures are preserved; scene enhancement does not repeat `RefineMesh`/`TextureMesh`. | Scene enhancement tests + code path review + live scene task |
| I14-AC-07 | PBR materials conform to glTF metallic-roughness semantics and embedded-image requirements. | Validator tests for valid/invalid factors, colour space slots, texture refs |
| I14-AC-08 | AI texture generation remains optional and disabled by default; no unverified model is a runtime dependency. | Config rejection tests, disabled backend tests, dependency diff |
| I14-AC-09 | Resource limits, cancellation, fallback, checkpoint invalidation and error reporting are tested. | Unit tests for each; scene manifest invalidation test |
| I14-AC-10 | A benchmark report demonstrates quality/performance trade-offs for object and scene assets. | Reproducible script + recorded JSON/CSV in `.proof/increment14/benchmark/` |
| I14-AC-11 | No public API, frontend, database or persisted-stage change; metadata stays compact and path-free. | Diff review; backend suite; stage constants unchanged |
| I14-AC-12 | GLB integration covers legacy vertex-colour, textured object, multi-mesh scene, no external URIs, Three.js/Khronos validator. | Integration tests + `load_glb.mjs` + Khronos validator |
| I14-AC-13 | GLB validation is extended independently for normals, UVs, material/PBR refs, embedded images and texture integrity, retaining legacy compatibility. | Validator unit tests |
| I14-AC-14 | Enhancement settings are validated, mapped to both workers, documented in env examples; FastAPI imports no ML library. | Backend settings tests + import check |

## 6. Risks and mitigations

| Risk | Mitigation |
|---|---|
| Texture baking slows a task or exhausts RAM | CPU-only, bounded 64–4096 atlas, vectorised batch rasteriser, memory budget checked before operations, cancellation poll per batch |
| Cleanup changes a valid asset | Conservative defaults, attribute-aware remapping, never touch UV seams, preserve source until the enhanced candidate validates |
| New validators reject legacy assets | New fields optional; `COLOR_0`-only and material-less GLBs remain accepted; `NORMAL` only validated when present |
| Scene post-processing corrupts OpenMVS materials | Off by default; mutates geometry in place, preserves scene graph/transforms/materials; textured geometry is never unwrapped or merged |
| Image rebuilds are expensive | Shared package copy is a late layer; the existing cached CUDA/OpenMVS/neural layers are reused |
| Real benchmark is host-GPU bound | Benchmark uses the retained real GLBs, records warm-up separately, and reports environment/median/p95 honestly |
