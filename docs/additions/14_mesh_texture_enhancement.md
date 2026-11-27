# 14 — Mesh and Texture Enhancement Specification

## 1. Purpose and Scope

Add optional post-reconstruction enhancement for object and scene assets. The feature set must improve geometry validity, topology efficiency, surface normals, UV availability, texture quality, PBR material consistency, and final GLB reliability.

This specification extends the existing object and scene pipelines. It does not replace TripoSR, Stable Fast 3D, Hunyuan3D, COLMAP, or OpenMVS. Existing generator-specific extraction and OpenMVS refinement/texturing remain the source stages.

Primary goals:

- Provide conservative, measurable mesh cleanup and optional simplification.
- Correct or regenerate normals without distorting valid geometry.
- Generate UVs when the source asset does not contain usable UV coordinates.
- Support optional texture baking and PBR material normalization.
- Add an opt-in AI texture enhancement adapter without making generated textures a mandatory dependency.
- Preserve appearance and geometry when enhancement is skipped or fails according to configured fallback policy.
- Export and validate self-contained GLB assets.

Out of scope: changing image preprocessing, feature matching, reconstruction algorithms, generator model selection, scene representation, or viewer design. Stage 1 image analysis and Stages 2–3 are referenced, not reimplemented.

## 2. Existing Components to Modify

The repository already has separate object and scene mesh/export implementations. Extend them; do not merge the pipelines or introduce a second export system.

| Existing file | Required modification |
|---|---|
| `ml/object_generation/mesh_processor.py` | Add opt-in cleanup, normal processing, topology metrics, and optional UV/mesh processing orchestration while preserving `validate_mesh()` semantics. |
| `ml/object_generation/exporter.py` | Preserve existing vertex-color export; support validated UV/PBR materials and embedded textures. Keep invalid-output cleanup behavior. |
| `ml/object_generation/pipeline.py` | Insert enhancement between generator output and GLB export; report timings, selected operations, fallback, and before/after metrics in `run.json`. Preserve current task stage identifiers unless a database/API migration is explicitly justified. |
| `ml/object_generation/config.py` | Add validated enhancement settings; do not continue rejecting all texture-baking configurations once the implementation is complete. |
| `ml/object_generation/validator.py` | Extend structural validation for normals, UVs, material texture references, embedded image data, and PBR fields without requiring every optional attribute for legacy vertex-color assets. |
| `ml/object_generation/requirements.txt` | Reuse pinned `trimesh` and `xatlas`; add only dependencies proven necessary and compatible with the worker's pinned Python/PyTorch/CUDA image. |
| `ml/object_generation/tests/` | Add deterministic tests for cleanup, normals, simplification, UVs, baking, material export, fallback, and GLB round-trip. |
| `ml/scene_reconstruction/mesh_processor.py` | Add shared validation/metrics and optional conservative post-processing entry points; retain existing OpenMVS mesh inspection behavior. |
| `ml/scene_reconstruction/exporter.py` | Preserve OpenMVS repacking; add optional post-repack GLB optimization/material validation only when it does not discard scene textures or node transforms. |
| `ml/scene_reconstruction/pipeline.py` | Extend the existing mesh refinement/texturing stages or add a distinct enhancement substage with checkpoint-aware manifests. Do not repeat OpenMVS `RefineMesh` or `TextureMesh`. |
| `ml/scene_reconstruction/config.py` | Add scene enhancement options with conservative defaults and include output-affecting values in the stage manifest. |
| `ml/scene_reconstruction/validator.py` | Add optional normal/UV/material/PBR checks and texture integrity checks while retaining current self-contained GLB requirements. |
| `ml/scene_reconstruction/requirements.txt` | Add only required, pinned CPU-compatible enhancement dependencies; keep neural texture dependencies out of the base scene worker unless explicitly enabled. |
| `backend/app/core/config.py` | Add validated worker settings and map them into existing object/scene config dataclasses. FastAPI must not import ML libraries. |
| `.env.example`, `.env.production.example` | Document safe defaults, opt-in flags, resource budgets, and fallback behavior. |

Before editing, inspect current `ObjectGenerationConfig`, `SceneConfig`, worker adapters, diagnostics, stage/checkpoint code, validators, and actual dependency pins. Do not assume an environment variable or stage can be added without updating its mapping and tests.

## 3. New Components

Create small pipeline-local modules rather than a generic asset-processing framework.

| Proposed file | Responsibility |
|---|---|
| `ml/object_generation/enhancement.py` | Object enhancement orchestration and typed before/after result. |
| `ml/scene_reconstruction/enhancement.py` | Scene-specific optional enhancement orchestration; preserves multi-mesh scene transforms and materials. |
| `ml/object_generation/texture_baking.py` | UV generation and baking adapter for object meshes. |
| `ml/object_generation/texture_generation.py` | Optional AI texture backend protocol, lazy loader, and validation boundary. |

The implementation agent may adapt names to repository conventions. Share low-level pure utilities only if both pipelines can use them without importing one worker package into the other. Do not create a large plugin framework.

### 3.1 Enhancement contract

Each enhancement operation must return:

- processed asset or mesh;
- operation identifiers and version/pin information;
- input/output vertex and face counts;
- UV/normal/material/texture presence flags;
- warnings and skipped-operation reasons;
- elapsed time and peak memory metrics when available.

Do not return raw tensors, image buffers, or absolute workspace paths in public metadata.

## 4. Architecture and Data Flow

### 4.1 Object pipeline

```text
Existing preprocessing + selected generator
                  |
                  v
        Generator mesh / materials
                  |
                  v
        Validate source geometry
                  |
                  v
        Conservative mesh cleanup
                  |
                  v
        Normal validation/correction
                  |
                  v
        Optional simplification
                  |
                  v
        UV availability check
             /          \
       usable UV       missing UV
           |                |
           |          xatlas unwrap
           |                |
           +--------+-------+
                    |
                    v
        Optional texture baking / AI texture
                    |
                    v
        PBR material normalization
                    |
                    v
          Existing GLB export path
                    |
                    v
          Extended GLB validation
```

If a selected operation is disabled, skip it without altering the asset. If an optional operation fails and fallback is enabled, preserve the last valid intermediate asset and continue with the original appearance path.

### 4.2 Scene pipeline

```text
COLMAP + OpenMVS reconstruction
       |
       +-- OpenMVS RefineMesh (existing)
       |
       +-- OpenMVS TextureMesh (existing)
       |
       v
Existing textured mesh / scene
       |
Optional conservative scene enhancement
       |
Existing OpenMVS export + GLB repack
       |
Extended GLB validation
```

OpenMVS remains responsible for photogrammetric scene texture projection and atlas creation. Do not run xatlas or AI texture generation over the entire scene by default; this may destroy camera-derived texture detail. Scene simplification/normal correction must preserve scene transforms, UVs, material assignments, and texture references.

## 5. Implementation Requirements

### 5.1 Mesh cleanup

Implement a conservative, ordered cleanup pass:

1. Reject non-finite vertices and invalid face indices using existing validators.
2. Remove duplicate/degenerate faces and unreferenced vertices where safe.
3. Detect duplicate vertices and merge only within a configurable, scale-aware tolerance.
4. Detect connected components and report component sizes. Remove small components only when an explicit threshold is configured; default to preserving them because thin or disconnected details may be intentional.
5. Detect zero-area faces, isolated vertices, and non-manifold edges. Record metrics before and after.
6. Do not force watertightness. Do not fill holes by default; hole filling can change the inferred object's shape and is not appropriate for every visual asset.
7. Do not smooth by default. If optional smoothing is implemented, use a bounded iteration count and preserve boundaries/features where supported.

Every destructive operation must be configurable, deterministic, and tested on open and non-manifold meshes. Preserve a source copy until the enhanced candidate passes validation.

### 5.2 Geometry optimization and adaptive remeshing

- Add optional quadric-error mesh simplification for assets above a configurable face/triangle budget.
- Preserve UV seams, vertex colors, normals, and material boundaries where the selected simplifier supports them. If attributes cannot be preserved, simplify before UV generation/baking or skip simplification.
- Use target face count or reduction ratio with validated bounds; do not hardcode one target for all objects and scenes.
- Measure geometric deviation (e.g. sampled surface distance/Hausdorff approximation) and reject simplification when the configured error budget is exceeded.
- Keep scene and object budgets separate. Large scene meshes must not inherit object defaults.
- Adaptive remeshing is optional and must be disabled by default. Add it only with a tested implementation that preserves appearance and does not turn open surfaces into invalid solids.
- Do not introduce a remesher solely to satisfy the roadmap; document unsupported cases and retain the original mesh.

Candidate simplification libraries (such as `fast-simplification` or PyMeshLab) must be evaluated against Python 3.12, NumPy 2.3.x, the worker image, licensing, and attribute preservation before pinning. Do not assume compatibility based on package availability.

### 5.3 Normal correction

- Validate existing vertex and face normals for shape, finite values, and non-zero length.
- Recompute face normals and consistent vertex normals when absent or invalid.
- Correct inconsistent winding/orientation only when a reliable component-level orientation can be inferred.
- Use `trimesh.repair.fix_normals` or equivalent only after confirming its behavior on open surfaces and disconnected components.
- Do not invert all normals based solely on a global heuristic for an open/non-watertight mesh.
- Export valid glTF `NORMAL` attributes where supported. Three.js fallback normal computation is not a substitute for validating the exported asset when normals are explicitly generated.

### 5.4 UV generation with xatlas

`xatlas==0.0.9` is already pinned in `ml/object_generation/requirements.txt`; reuse it for object generation. The scene worker does not currently depend on xatlas. Add it to the scene worker only if scene-specific UV generation is enabled and benchmarked.

Requirements:

- Detect valid existing `TEXCOORD_0` before generating a new atlas.
- Preserve valid generator-provided UVs unless explicit regeneration is requested.
- Run xatlas on the final topology after any simplification/remeshing that changes vertex indices.
- Correctly handle xatlas vertex duplication/reindexing and remap positions, normals, vertex colors, and face/material attributes.
- Support configurable atlas resolution, padding, and chart settings within validated bounds.
- Validate finite UV coordinates and expected [0,1] range (allow documented padding tolerance).
- Avoid UV regeneration for textured OpenMVS scene meshes by default.
- Record UV generation version/settings in the enhancement manifest.

### 5.5 Texture baking

Implement texture baking as an optional operation, not as a mandatory part of every generation.

Object-generation requirements:

- Support baking existing vertex-color appearance into a UV texture atlas when UVs are available/generated.
- Where the generator provides a source appearance/texture representation, support baking that appearance to the final mesh UVs without inventing new surface detail.
- Produce an explicit base-color texture and a material referencing it.
- Use configurable texture resolution and padding; default to a conservative 1024 or 2048 atlas based on benchmark results and memory budget.
- Embed the resulting image in GLB; do not leave temporary sidecar paths in the asset.
- If baking fails, preserve the original vertex-color/material representation when valid and record `texture_baking_fallback`.

Scene requirements:

- Reuse OpenMVS camera-projected textures and UVs. Do not rebake or flatten scene texture atlases unless a tested use case requires it.
- If a scene export contains multiple materials/atlases, preserve all material-to-primitive associations.

The existing `object_bake_texture` setting currently rejects `true`; remove that restriction only after the end-to-end bake/export/validation path is implemented and covered by tests. Do not silently reinterpret the existing flag.

### 5.6 AI-based texture generation

AI texture generation is an optional enhancement path and must not be required to run either worker.

Define a backend interface that accepts:

- the source asset/UV layout;
- optional user-provided text prompt or reference image, if supported by the product contract;
- a bounded texture resolution and generation configuration;
- cancellation and progress callbacks.

The backend must return texture maps associated with the exact UV layout and material slots. It must not change mesh topology or UV indexing. Generated maps must be checked for dimensions, channel count, finite values, color-space metadata, and valid material assignment.

Requirements:

- Do not select or pin a specific AI texture model until license, commercial-use terms, Python/CUDA compatibility, inference API, VRAM use, and RTX 3060 feasibility have been verified.
- Keep AI texture inference isolated from the base object/scene worker dependency set where possible (separate optional requirements/image or subprocess service).
- Lazy-load model weights and never download them during a generation task. Use a checksum/versioned model cache following the existing worker model-cache pattern.
- Treat AI-generated texture as an appearance enhancement, not a source of geometric truth. It must not be used to claim photogrammetric texture fidelity.
- Preserve the original camera/generator-derived texture as a recoverable fallback.
- AI texture generation is disabled by default. It must be explicitly enabled and benchmarked before production use.
- Do not generate unsupported normal/roughness/metallic maps by relabeling a base-color image. Each PBR map must come from a validated model or a documented deterministic derivation.

For initial delivery, implement the interface, configuration, validation, and a disabled/unavailable backend state if no compliant model can be selected. Report the blocker rather than introducing an unverified model dependency.

### 5.7 PBR material handling

Normalize supported materials to glTF 2.0 metallic-roughness semantics:

- `baseColorFactor` and/or base-color texture;
- `metallicFactor` and `roughnessFactor`;
- optional metallic-roughness texture;
- optional normal texture and scale;
- optional occlusion texture and strength;
- optional emissive texture/factor only when present in source data.

Requirements:

- Preserve source material factors and textures whenever valid.
- Do not assume all assets are metallic; use conservative dielectric defaults when source material data is absent.
- Respect glTF texture channel conventions (metallic in B, roughness in G for a combined metallic-roughness texture).
- Preserve sRGB treatment for base color/emissive and linear treatment for normal, metallic-roughness, and occlusion data.
- Validate image dimensions, MIME types, sampler references, texture indices, UV-set references, and material-to-primitive assignments.
- Avoid duplicating identical embedded images/materials during repack.
- Keep GLB self-contained; no external image or buffer URI may remain in the final artifact.

### 5.8 GLB export and quality validation

Extend existing exporters/validators; do not replace their independent binary parsing with a `trimesh`-only check.

Object GLB validation must continue to accept legacy vertex-color assets and additionally validate, when present:

- `NORMAL` accessor shape/count and finite non-zero vectors;
- `TEXCOORD_0` accessor shape/count and finite coordinates;
- valid material indices and PBR texture references;
- embedded image bufferViews and supported MIME types;
- texture-coordinate availability for each textured primitive.

Scene validation must retain current self-contained GLB requirements and support multiple meshes/materials/textures. A scene with texture generation enabled must still satisfy the existing `require_textures=True` behavior.

Add optional quality warnings (not unconditional hard failures) for high face count, missing normals, missing UVs on untextured assets, disconnected components, degenerate-face ratio, and texture resolution below configured target. Keep hard failures for malformed geometry, invalid references, corrupt images, and external dependencies.

## 6. Configuration

Add separate object and scene settings. Suggested semantics and defaults:

| Setting | Suggested default | Description |
|---|---:|---|
| `object_mesh_cleanup_enabled` | `true` | Run conservative cleanup only. |
| `object_mesh_merge_tolerance` | scale-aware, documented | Duplicate-vertex merge tolerance; must not be a fixed world-unit value for all scales. |
| `object_mesh_remove_small_components` | `false` | Preserve disconnected components by default. |
| `object_mesh_simplification_enabled` | `false` | Optional face-budget reduction. |
| `object_mesh_target_faces` | `0` | 0 disables simplification; positive value enables a target. |
| `object_mesh_max_deviation` | benchmark-derived | Maximum allowed simplification deviation. |
| `object_mesh_smoothing_iterations` | `0` | Disabled by default. |
| `object_generate_uv` | `false` | Generate UVs only when a downstream texture operation requires them. |
| `object_uv_resolution` | `1024` | Initial conservative atlas resolution; benchmark 1024/2048. |
| `object_bake_texture` | `false` | Enable implemented vertex-color/source-appearance baking. |
| `object_texture_resolution` | `1024` | Validated texture size; allow 2048 after memory/quality tests. |
| `object_ai_texture_enabled` | `false` | Optional AI texture adapter. |
| `scene_mesh_postprocess_enabled` | `false` | Additional processing after existing OpenMVS stages. |
| `scene_mesh_simplification_enabled` | `false` | Optional scene simplification; preserve UV/material data. |
| `scene_mesh_target_faces` | `0` | 0 disables simplification. |
| `scene_generate_uv` | `false` | Do not regenerate OpenMVS UVs by default. |
| `scene_ai_texture_enabled` | `false` | Optional and disabled by default. |
| `mesh_enhancement_max_memory_mb` | deployment-derived | Soft per-task host-memory budget. |
| `texture_enhancement_device` | `cpu` | CPU for deterministic atlas/material operations; AI backend may select CUDA explicitly. |
| `enhancement_fallback_to_original` | `true` | Preserve last valid source asset after optional enhancement failure. |

Validate ranges and incompatible combinations. Include every output-affecting setting, dependency/model version, and source asset fingerprint in the relevant enhancement checkpoint manifest. Do not add user-facing API controls in this stage.

## 7. API and Integration Requirements

- No public API change is required. Configure enhancement through worker settings.
- Preserve current task lifecycle, result registration, storage, and GLB download contracts.
- Preserve existing stage names where possible. If a new persisted stage is required, update backend enum/schema constraints, task-stage mapping, frontend progress labels, tests, and both worker adapters together. Prefer substage diagnostics over a database migration for the first implementation.
- Add compact metadata: operations applied, before/after geometry counts, UV/texture/material flags, warnings, fallback status, and timings.
- Do not expose local file paths, prompts containing private data, raw model outputs, or internal exceptions in public responses.
- Update `docs/specifications/06_object_generation.md` and `07_scene_reconstruction.md` only where their current statements become obsolete (notably the MVP texture-baking prohibition); preserve their existing architecture and stage definitions.

## 8. GPU/CPU Resource Management

Target development hardware is RTX 3060 12 GB VRAM. Geometry cleanup, xatlas UV generation, mesh simplification, image packing, and GLB validation should run on CPU unless a selected library demonstrably requires CUDA.

- Do not load an AI texture model for ordinary mesh cleanup or UV generation.
- AI texture inference must use bounded batches/resolution and explicit VRAM admission checks.
- Keep geometry and texture processing sequential; avoid retaining generator models/tensors during CPU post-processing where possible.
- Release intermediate arrays/images after each operation and avoid unnecessary copies of large meshes.
- Enforce host RAM and temporary-disk budgets as well as VRAM limits; large scene meshes may be CPU-memory bound.
- Use task cancellation/heartbeat callbacks during long mesh/texture loops where practical.
- Do not run concurrent AI texture tasks on the same 12 GB GPU without existing worker admission control.
- Record peak VRAM for AI operations and peak host memory where available. Do not claim a model fits RTX 3060 based only on published minimums.

## 9. Error Handling

Use existing object and scene error models. Add stable internal error codes only where existing codes cannot distinguish:

- mesh cleanup failure;
- simplification failure or deviation-budget rejection;
- normal generation/correction failure;
- UV generation failure;
- texture baking failure;
- AI texture runtime/model unavailable or inference failure;
- invalid PBR material or texture reference;
- enhancement resource exhaustion.

Requirements:

- Preserve the last validated intermediate asset before each destructive step.
- If `enhancement_fallback_to_original=true`, skip the failed optional operation and continue from the last valid asset; record the exact operation and reason.
- Never fallback after a hard source-geometry validation failure or silently register a corrupt GLB.
- If texture baking fails but vertex colors/source material remain valid, export the original appearance and mark `appearance_mode` accurately.
- Cancellation and task timeout must stop enhancement promptly and clean temporary outputs.
- Remove incomplete temporary files; never leave partial outputs eligible for checkpoint reuse.

## 10. Testing Requirements

### 10.1 Unit tests

- Cleanup removes only configured invalid/duplicate elements and preserves valid disconnected components by default.
- Open, non-manifold, and non-watertight meshes remain accepted when geometrically valid.
- Normal generation handles missing, zero-length, non-finite, and inconsistent normals without arbitrary global inversion.
- Simplification respects target count and rejects excessive geometric deviation.
- Attribute/material preservation is tested across simplification or the operation is skipped when unsupported.
- xatlas UV output has valid indices, finite coordinates, expected range, and correctly remapped vertex attributes.
- Existing UVs are preserved when regeneration is disabled.
- Vertex-color baking produces an embedded base-color texture and valid material reference.
- PBR channel/color-space handling and multi-material assignment are validated.
- AI texture adapter is lazy, disabled by default, validates outputs, and preserves source texture on failure.
- Enhancement manifest invalidates checkpoints when operation settings, dependency/model versions, or source fingerprint change.
- Cancellation, timeout, memory-budget failure, and configured fallback preserve the last valid asset.

### 10.2 GLB integration tests

- Export and reopen a vertex-color-only TripoSR-style mesh; preserve legacy compatibility.
- Export a UV-mapped textured object with embedded base-color texture and PBR material.
- Export multi-mesh/multi-material scene assets with embedded OpenMVS textures and node transforms.
- Verify no external image or buffer URI remains.
- Load final GLBs with the existing Three.js GLTFLoader viewer (`ml/object_generation/viewer/load_glb.mjs`) and Khronos glTF Validator where available.
- Verify checksums and metadata are computed from the final post-enhancement GLB.

### 10.3 Quality benchmarks

Use a fixed, documented set of object and scene assets. Compare baseline vs enhancement with identical source reconstructions.

Record:

- vertex/face counts and connected-component counts;
- degenerate/non-manifold edge counts where measurable;
- normal consistency metrics;
- UV coverage, chart count, and atlas utilization;
- texture resolution and file size;
- sampled geometric deviation after simplification;
- visual review from fixed camera views and Three.js rendering;
- processing duration, peak RAM, peak VRAM, and final GLB size;
- task success/fallback rate.

Do not use face-count reduction, texture resolution, or a single image metric as a proxy for perceived quality. Keep reference renders and benchmark metadata reproducible. AI texture results require a separate visual review for hallucinated details, seams, repetition, and inconsistency.

## 11. Acceptance Criteria

- Existing object and scene generation continue to work with enhancement disabled/default settings.
- Existing TripoSR vertex-color GLBs and OpenMVS textured scene GLBs remain valid and load in Three.js.
- Conservative cleanup and normal correction are implemented with measurable before/after diagnostics.
- Optional simplification is guarded by geometry-deviation limits and preserves required attributes/materials or safely skips.
- xatlas UV generation works for object meshes and preserves/remaps all vertex attributes correctly.
- Object texture baking produces a self-contained GLB with valid UVs/material references; the current `object_bake_texture=true` rejection is removed only after this is proven.
- OpenMVS scene UVs/textures are preserved; scene enhancement does not duplicate existing refinement/texturing.
- PBR materials conform to glTF metallic-roughness semantics and embedded-image requirements.
- AI texture generation remains optional and disabled by default; no unverified model is made a runtime dependency.
- Resource limits, cancellation, fallback, checkpoint invalidation, and error reporting are tested.
- Benchmark report demonstrates quality/performance trade-offs for object and scene assets.

## 12. AI Agent Implementation Instructions

1. Read `06_object_generation.md`, `07_scene_reconstruction.md`, `ml/object_generation/README.md`, `ml/object_generation/mesh_processor.py`, `exporter.py`, `validator.py`, `pipeline.py`, and the corresponding scene files before editing.
2. Confirm the exact worker Python, NumPy, trimesh, xatlas, PyTorch/CUDA, OpenMVS, and Three.js/glTF validator versions from the repository and built images.
3. Implement object-side CPU cleanup and normal validation first; preserve current `validate_mesh()` behavior and existing tests.
4. Add optional simplification only after proving attribute preservation and geometric-deviation checks on representative assets.
5. Implement xatlas UV generation with explicit vertex/attribute remapping. Test on meshes with vertex colors, multiple components, and seams.
6. Implement vertex-color/source-appearance baking and GLB embedding before enabling the existing `object_bake_texture` setting.
7. Extend object GLB validation independently; keep backward compatibility with vertex-color-only assets.
8. Extend scene processing conservatively after existing OpenMVS refinement/texturing. Do not regenerate scene UVs or textures by default.
9. Add PBR material normalization and multi-material integration tests.
10. Define the AI texture adapter, but select and integrate a concrete model only after licensing, compatibility, model cache, resource, and quality checks. If none is suitable, leave the backend disabled and document the blocker.
11. Add settings to backend config, worker adapters, environment examples, manifests, diagnostics, and tests. Keep FastAPI free of ML imports.
12. Run object and scene unit suites, GLB/Three.js integration tests, and reproducible benchmarks. Update existing specification statements only where implementation changes their status.
13. Do not proceed to neural scene reconstruction or any other roadmap stage as part of this task.

**Deliverable:** `14_mesh_texture_enhancement.md`. This is a documentation-only task; do not implement code.
