# Increment 12 close-out review — advanced feature matching

**Date:** 2026-11-25
**Specification:** [`docs/additions/12_advanced_feature_matching.md`](../additions/12_advanced_feature_matching.md)
**Plan and acceptance criteria:** [`docs/additions/12_implementation_plan.md`](../additions/12_implementation_plan.md)
**Scope:** one post-MVP increment only. COLMAP SIFT remains the production
default; ALIKED + LightGlue is an opt-in scene-worker backend with configured
fallback.

## 1. Summary

The increment adds a feature-backend contract, deterministic pair generation, a
COLMAP-compatible neural adapter, checkpoint manifests, resource controls,
diagnostics and fallback, without changing the public API, stage identifiers,
task lifecycle, result contract or any OpenMVS stage. The pinned neural stack
was validated against the actual COLMAP 4.2.1 binary before implementation, and
the final verification includes a real ALIKED/LightGlue database consumed by
the pinned mapper, a live GPU scene task and a live fallback drill.

The addendum's last line called the deliverable documentation-only. The direct
session instruction required implementation, so the compatibility study became
the first task and the implementation followed. That conflict is recorded in
the plan rather than silently resolved.

## 2. Compatibility findings

Spike on 2026-11-25 (temporary CPU torch, no production file changed):

| Component | Version / revision |
|---|---|
| COLMAP | 4.2.1 (`colmap/colmap:20260929.8466`) |
| pycolmap | 4.2.1 (`Database.write_keypoints`, `write_matches`, `pycolmap.verify_matches`, `import_images`) |
| PyTorch / torchvision | 2.14.1+cu130 / 0.29.2+cu132 in the final image |
| Kornia / kornia-rs | 0.9.2 / 0.2.0 |
| OpenCV (Python) | 5.1.0.95 |
| Matplotlib | 3.11.2 |
| LightGlue | commit `5a650c444718caffc2669dc0094cde908f42dd73` |
| ALIKED weights | `aliked-n16.pth` SHA-256 `5be8704840ed662d9d8c561bf7279c222092674e7eb05fd0feab94899e9d82f2` |
| LightGlue weights | `aliked_lightglue_v0-1_arxiv.pth` SHA-256 `d975e965b105311a6143194852297dff4f02aea5cc2e10cecfed966ca0e22503` |

Spike result: 3 Sceaux photographs, ALIKED 1 024 keypoints/image, LightGlue
711/655/853 matches per pair, `pycolmap.verify_matches` wrote 3/3 verified
pairs, the pinned mapper produced a model with 3/3 registered, 639 points and
mean reprojection error 0.396. No HLoc package was added: HLoc's import path is
a thin wrapper over the same pycolmap calls, so the adapter calls pycolmap
4.2.1 directly and keeps the maintained actual-binary test. This avoids adding
HLoc's `gdown`, `plotly`, `scipy` and `h5py` dependency surface solely to reach
the import (matplotlib is installed anyway because LightGlue declares it).

## 3. Implemented

**New files:** `feature_profiles.py` (validated profiles and pinned model
identifiers), `feature_matching.py` (backend protocol, SIFT adapter, factory,
deterministic pairs, checkpoint manifest), `neural_features.py` (ALIKED +
LightGlue, pycolmap import and verification, atomic database replacement,
resource checks), `download_neural_models.py` (baked, checksum-verified
weights), `benchmark_features.py` (reproducible five-variant benchmark),
`requirements-neural.txt`, three unit-test modules and one opt-in
actual-binary interoperability test.

**Modified:** `config.py` (feature settings and manifest), `pipeline.py`
(backend dispatch, manifest-gated reuse, dependency-aware invalidation,
fallback, diagnostics), `diagnostics.py` (compact `features` block),
`exceptions.py` (stable neural/configuration codes and recoverable-failure
classification), `standalone.py` (backend/profile/device/pair flags),
`Dockerfile` (pinned neural stack, baked weights, purged build-only git),
`README.md`, `backend/app/core/config.py` (`scene_feature_*` settings and
validation), `backend/tests/unit/test_config.py`,
`backend/tests/unit/test_scene_settings.py`, `.env.example`,
`.env.production.example`, `compose.yaml` (scene-worker only), plus this review,
the plan and HANDOFF/NEXT_SESSION.

**Behaviour:**

- `COLMAP_SIFT` delegates to the existing `ColmapRunner`; its command arrays,
  stage semantics and defaults are unchanged. Its checkpoint reuse now also
  requires the manifest to match (one-time invalidation on upgrade, then stable).
- `ALIKED_LIGHTGLUE` extracts ALIKED-N16 features one image at a time, restores
  keypoints to original coordinates, matches deterministic pairs with
  LightGlue, imports keypoints/matches into a temporary pycolmap database and
  runs `pycolmap.verify_matches` before atomically replacing `database.db`.
- Pair generation: `EXHAUSTIVE` over sorted names, `SEQUENTIAL` over dataset
  order with the configured overlap, always bounded before model loading.
- `colmap/feature_manifest.json` fingerprints the ordered image SHA-256 set,
  backend/profile, model/checkpoint identifiers and runtime versions, keypoint
  budget, resize limit, pair strategy/overlap, thresholds, verification
  settings and the COLMAP version. A mismatch deletes extraction, matching and
  dependent sparse/dense/OpenMVS outputs; unrelated outputs are untouched.
- Configured fallback discards neural outputs and rebuilds SIFT extraction and
  matching cleanly, recording `fallback.used` and the stable reason. Invalid
  datasets, deterministic configuration errors, pair-limit errors and disabled
  fallback are re-raised unchanged.
- Diagnostics expose requested/actual backend and profile, versions, device,
  precision, peak VRAM, keypoint/pair/verified counts, stage seconds and the
  fallback reason. No descriptors, tensors, paths or command lines are exposed.
- Neural runtime is loaded lazily; SIFT-only tasks never import torch/pycolmap.
  Explicit `cuda` fails with `NEURAL_CUDA_UNAVAILABLE`; `auto` uses CUDA when
  available and CPU otherwise; a 2 GB free-VRAM floor and the configured soft
  budget are checked; OOM maps to `NEURAL_RESOURCE_EXHAUSTED`; models are
  released and the CUDA cache is cleared after each stage.
- No public API, frontend, result/download or persistence change. The API image
  has no neural dependency.

## 4. Requirement traceability

Plan-local criteria (addendum Section 11 uses unnumbered bullets):

| ID | Result | Evidence |
|---|---|---|
| I12-AC-01 | Passed | SIFT command-equality test; existing scene suite unchanged and green. |
| I12-AC-02 | Passed | Settings/profile validation tests; API requirements untouched; no route/schema diff. |
| I12-AC-03 | Passed | Actual-binary interoperability test (ALIKED → LightGlue → pycolmap import → `verify_matches`). |
| I12-AC-04 | Passed | Same test runs the pinned `colmap mapper`, asserts non-zero keypoints/pairs/verified pairs and inspects the model with the existing selector. |
| I12-AC-05 | Passed | Live neural scene task completed through sparse, dense, mesh, texture, export, validation and result registration. |
| I12-AC-06 | Passed | Manifest equality/mismatch tests; measured rebuild of both stages and dependants. |
| I12-AC-07 | Passed | Unit fallback at extraction and matching, plus a live no-GPU drill that rebuilt SIFT and completed the reconstruction with `NEURAL_CUDA_UNAVAILABLE`. |
| I12-AC-08 | Passed | Device/CUDA/OOM/validation unit tests; live GPU task reported 1 737 MB extraction peak and 180 MB matching peak. |
| I12-AC-09 | Passed | Scene suite and interoperability test results below. |
| I12-AC-10 | Passed | Five-variant benchmark on identical images/hardware; results below. |
| I12-AC-11 | Passed | Defaults remain `COLMAP_SIFT` + `sift_default` + fallback enabled in Settings, SceneConfig, `.env.example` and Compose. |
| I12-AC-12 | Passed | Redaction unit test and live metadata inspection (no descriptors/tensors/paths/commands). |

## 5. Verification executed

**Final scene image:** `mogen-scene-worker:dev`, image ID
`sha256:9302854844a9…`, created 2026-11-25T00:10:20Z, 20.7 GB. It includes the
pinned neural stack and the two checksum-verified checkpoints. The API and
object-worker images were not rebuilt for this increment.

| Check | Result |
|---|---|
| `import torch` with `--gpus all` | `2.14.1+cu130`, CUDA available, RTX 3060 |
| Scene unit suite (`/opt/scene_reconstruction/tests`) | **117 passed, 0 failed, 2 skipped** (119 collected; the earlier "119 passed" wording over-counted by two) |
| Actual-binary interoperability (`RUN_FEATURE_INTEROP_TEST=1`, 6 Sceaux images, CUDA) | **1 passed** (19.3 s cold, 8.3 s warm in the final image) |
| Image-quality suite in the scene image | **47 passed** (increment 11 unchanged) |
| Backend suite | **541 passed** (526 baseline + 15 new settings/behaviour cases) |
| Ruff check / format (changed scene files) | clean; no new findings |
| `pip check` in the scene image | clean |
| `--verify-tools` | COLMAP 4.2.1 + OpenMVS 2.4.0 |
| Live neural scene task | **COMPLETED** in 5 min 49 s on the final image; 11/11 images, 22 528 keypoints, 34 pairs, 34 verified, CUDA, no fallback, `image_quality.status="OK"`, GLB 760 724 bytes |
| Live fallback drill (no GPU, explicit CUDA) | SIFT rebuilt, 5/5 registered, 2 458 points, GLB 384 980 bytes, `fallback.used=true`, reason `NEURAL_CUDA_UNAVAILABLE` |

Live task metadata (recorded under `.proof/increment12-live/20261125-032139/`):
backend `ALIKED_LIGHTGLUE`, profile `aliked_lightglue`, strategy `SEQUENTIAL`,
extraction 3.557 s (peak 1 737 MB), matching 1.936 s (peak 180 MB), database
11 images / 22 528 keypoints / 34 matched / 34 verified, selection 11/11
registered with 2 665 points and mean reprojection error 0.643, GLB validation
with one embedded texture and no extension warnings. The development stack was
then recreated with the default `COLMAP_SIFT` configuration.

## 6. Benchmark (11 Sceaux photographs, RTX 3060, identical prepared images)

Reproducible command in `ml/scene_reconstruction/README.md`; raw JSON is
`.proof/increment12/benchmark/feature-benchmark.json`.

| Variant | Success | Registered | Points | Reprojection | Extract | Match | Sparse | Total | Peak VRAM |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| SIFT exhaustive | yes | 11/11 | 7 668 | 0.577 | 5.72 s | 2.27 s | 18.72 s | 41.89 s | CPU |
| SIFT sequential | yes | 11/11 | 8 020 | 0.567 | 6.17 s | 2.47 s | 12.09 s | 22.75 s | CPU |
| ALIKED exhaustive | yes | 11/11 | 2 821 | 0.546 | 23.29 s* | 5.93 s | 21.85 s | 77.06 s | 180 MB |
| ALIKED sequential | yes | 11/11 | 2 759 | 0.535 | 6.17 s | 3.92 s | 8.37 s | 20.42 s | 180 MB |
| ALIKED fast exhaustive | yes | 11/11 | 1 423 | 0.487 | 6.71 s | 4.41 s | 5.32 s | 18.74 s | 90 MB |

\* The first neural variant includes the one-time model load in its extraction
timer; later neural variants reuse the OS page cache.

On this single scene both backends register all images. Neural matching yields
fewer sparse points and no demonstrated quality improvement, while exhaustive
neural matching is slower; the fast profile is the fastest overall but has the
fewest points. This supports keeping SIFT as the production default and is not
presented as a general quality claim (the spec explicitly requires per-scene
results, not universal thresholds).

## 7. Findings fixed during verification

1. **False task-timeout on direct stage calls.** `PhotogrammetryReconstructor`
   initialised its clock to `0.0` and only `reconstruct()` reset it. The new
   unit tests call stage methods directly; after ~4 h of host uptime those calls
   saw `time.monotonic() - 0` exceed the 14 400 s task budget and raised
   `TOOL_TIMEOUT`, failing four tests that had passed earlier in the session.
   The clock is now initialised to `time.monotonic()` in `__init__` (and still
   reset by `reconstruct()`). This is a pre-existing defect surfaced by the new
   tests, fixed with no behaviour change for normal tasks.
2. **`pip check` failed after the first neural image build.** LightGlue declares
   `opencv-python` and `matplotlib`, while the adapter had installed only
   `opencv-python-headless`. The final image installs the declared
   distributions (both pinned) and `pip check` is clean.

## 8. Known limitations

- The benchmark covers one scene class (outdoor architecture) and one GPU; the
  acceptance criteria require per-scene reporting, not a universal winner.
- Neural mode needs the ~3.5 GB extra runtime and model layer in the scene
  image. The development image grew accordingly; the released `:1.0.0`
  production images were intentionally not rebuilt for a post-MVP increment.
- The adapter intentionally does not import descriptors into COLMAP (the mapper
  does not need them) and never reuses neural keypoints as SIFT features.
- SIFT fallback on a CPU-only host still requires `SCENE_COLMAP_USE_GPU=false`;
  during the drill an 8-thread CPU SIFT extraction at 8 192 features was
  OOM-killed by the host, which is a resource condition, not a pipeline defect.
  The worker's configured `SCENE_MAX_THREADS=4` fits.
- `--no-texture` on the OpenMVS export path produced a TransformScene segfault
  during one drill attempt; the production path (texturing enabled) and the
  completed fallback drill were unaffected. This is pre-existing OpenMVS
  behaviour outside this increment and is not changed here.
- Neural mode remains opt-in; promotion would require a broader multi-scene
  benchmark showing a meaningful reconstruction improvement.

## 9. Next step

The next post-MVP addendum is [`docs/additions/13_advanced_object_generation.md`](../additions/13_advanced_object_generation.md).
It has not been started. Increment 11 thresholds were not retuned, and released
MVP behaviour, the viewer, result/download contract, outbox and reconstruction
algorithms were not re-opened.
