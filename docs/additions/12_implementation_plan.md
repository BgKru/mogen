# Increment 12 — Implementation Plan and Acceptance Criteria

**Specification:** [`12_advanced_feature_matching.md`](12_advanced_feature_matching.md)
**Scope:** Optional ALIKED + LightGlue feature extraction/matching for scene reconstruction; COLMAP SIFT stays the default and fallback.
**Status:** Implemented and verified (2026-11-25); evidence in
[`../reviews/increment12_closeout.md`](../reviews/increment12_closeout.md).
**Date:** 2026-11-25.

## 1. Scope resolution

The addendum's last line says the deliverable is the specification plus
compatibility findings and "Do not implement code during this documentation
task." The session instruction explicitly says to read the addendum, write its
plan and acceptance criteria, and **implement only that increment**. The direct
instruction governs: this is an implementation increment, and the compatibility
study below is its first task, not its deliverable. This decision is recorded so
the contradiction is not silently resolved.

## 2. Compatibility findings (spike, 2026-11-25)

Run in the existing `mogen-scene-worker:dev` image with a temporary CPU PyTorch
install; no production file was modified.

| Component | Version / revision | Notes |
|---|---|---|
| COLMAP | 4.2.1 (`colmap/colmap:20260929.8466`) | pinned worker binary |
| pycolmap | **4.2.1** | exact version match; `Database.write_keypoints`, `write_matches`, `write_two_view_geometry`, `pycolmap.verify_matches` and `import_images` available |
| PyTorch | 2.14.1 (CPU for the spike) | same version as the object worker's CUDA 12.6 runtime |
| torchvision | 0.29.2 | required by `lightglue.aliked` |
| Kornia | 0.9.2 | required by LightGlue's package `__init__` |
| OpenCV (Python) | opencv-python-headless 5.1.0.95 | LightGlue imports `cv2`; headless avoids GUI libraries |
| LightGlue | commit `5a650c444718caffc2669dc0094cde908f42dd73` | `LightGlue(features="aliked")` |
| ALIKED weights | `aliked-n16.pth`, SHA-256 `5be8704840ed662d9d8c561bf7279c222092674e7eb05fd0feab94899e9d82f2` | Shiaoming/ALIKED |
| LightGlue weights | `aliked_lightglue_v0-1_arxiv.pth`, SHA-256 `d975e965b105311a6143194852297dff4f02aea5cc2e10cecfed966ca0e22503` | cvg/LightGlue release |

Spike result on three Sceaux photographs (CPU, 800 px inference edge):

- ALIKED produced 1 024 keypoints and 128-dimensional descriptors per image.
- LightGlue produced 711, 655 and 853 tentative matches for the three pairs.
- `pycolmap.verify_matches` wrote 3/3 verified pairs; `read_database_stats`
  reported 3 images, 3 072 keypoints, 1 connected component of size 3.
- The pinned `colmap mapper` accepted the database unchanged and produced a
  model with **3/3 images registered, 639 points, mean reprojection error
  0.396**, and `inspect_model` reported no warnings.

**Conclusion:** the pinned COLMAP 4.2.1 binary and pycolmap 4.2.1 interoperate;
the database import and geometric-verification path is viable. No HLoc package
is required: its import path is a thin wrapper over the same pycolmap calls. We
will use pycolmap's public API directly (as HLoc does) and keep the maintained
test against the actual binary. This avoids adding HLoc's `gdown`, `plotly`,
`scipy`, `h5py` and `matplotlib` dependencies solely to reach ~20 lines of
database import.

## 3. Design decisions

1. **Backends.** `COLMAP_SIFT` delegates to the existing `ColmapRunner`
   extraction/matching commands byte-for-byte. `ALIKED_LIGHTGLUE` is a new
   adapter; no neural import is reachable in SIFT-only deployments.
2. **Profiles.** `sift_default`, `aliked_lightglue`, `aliked_lightglue_fast`.
   The fast profile uses the same ALIKED-N16 model with a 1 024-keypoint budget;
   it is not a different model.
3. **Two stages.** Extraction owns ALIKED + keypoint import; matching owns pair
   generation + LightGlue + `pycolmap.verify_matches`. The existing
   `FEATURE_EXTRACTION` / `FEATURE_MATCHING` stages, heartbeats, cancellation
   and timeouts stay in control. Both write into a temporary database and
   replace `database.db` atomically only after validation.
4. **Checkpoint manifest.** `colmap/feature_manifest.json` records the ordered
   image SHA-256/size/name fingerprint, backend/profile, model revisions and
   checksums, parameters, pair strategy/overlap, resize limit, verification
   settings and COLMAP schema/version. Reuse requires an exact canonical match;
   otherwise extraction and matching outputs are discarded and rebuilt. A
   neural database can never be reused as a SIFT database.
5. **Pair selection.** Deterministic exhaustive (all sorted pairs, capped by a
   configurable limit) or sequential (dataset order, overlap window). Pairs are
   computed before inference and the limit is enforced first.
6. **Fallback.** Only when `fallback_to_sift=true` and the failure is
   recoverable (runtime/CUDA/OOM, extraction/matching/verification/import
   failure, insufficient verified pairs). Invalid datasets and deterministic
   configuration errors never fall back. Fallback deletes the neural database
   and features, runs clean SIFT extraction + matching, and records the reason
   and the actual backend. A fallback result is never reported as neural.
7. **Resources.** Lazy model load; one image/pair at a time; bounded pair count;
   explicit CUDA availability check; soft VRAM budget check; FP32 default with
   no unvalidated mixed precision; CUDA cache cleanup after stages; device
   `auto` falls back to CPU, explicit `cuda` fails clearly; peaks recorded.
8. **Diagnostics.** Backend/profile requested and actual, versions/commits,
   device/precision, keypoint and pair counts, verified pairs, fallback
   reason, stage timings and peak VRAM. No descriptors, tensors, paths,
   commands or raw model internals.
9. **API.** No public API or frontend change; selection is worker
   configuration only. Result metadata gains a compact `features` block.

## 4. Files

**New:** `ml/scene_reconstruction/feature_profiles.py`,
`feature_matching.py`, `neural_features.py`, `download_neural_models.py`,
`benchmark_features.py`, `requirements-neural.txt`; corresponding tests;
`docs/additions/12_implementation_plan.md` (this file) and
`docs/reviews/increment12_closeout.md` (after verification).

**Modified:** `config.py`, `pipeline.py`, `diagnostics.py`, `preflight.py`,
`exceptions.py`, `colmap_runner.py` (only if a shared validation helper is
needed), `standalone.py`, `Dockerfile`, `README.md`, `backend/app/core/config.py`,
`.env.example`, `.env.production.example`, `compose.yaml`,
`backend/tests/unit/test_config.py`, `backend/tests/unit/test_scene_settings.py`
(if present), `docs/HANDOFF.md`, `docs/NEXT_SESSION.md`.

## 5. Work breakdown

1. Configuration and profiles: validated settings, defaults, manifest
   serialisation, backend/profile compatibility.
2. Backend contract + SIFT adapter + factory; regression test that SIFT command
   arrays and defaults are unchanged.
3. Neural adapter: model loading/checksums, ALIKED extraction, coordinate
   restoration, deterministic pairs, LightGlue, pycolmap import, geometric
   verification, atomic DB replacement, cleanup.
4. Pipeline dispatch, checkpoint manifest, fallback, diagnostics, preflight.
5. Backend settings mapping and configuration examples.
6. Dockerfile: pinned neural dependencies, baked and checksum-verified models,
   no git in the runtime layer; image rebuild.
7. Unit tests, actual-binary interoperability test, benchmark command.
8. Live worker verification (neural task through the stack, fallback drill),
   benchmark run, documentation and close-out review.

## 6. Acceptance criteria

These identifiers are **plan-local** (`I12-AC-nn`), because addendum Section 11
lists unnumbered bullets. Each maps to a bullet there.

| ID | Criterion | Evidence |
|---|---|---|
| I12-AC-01 | SIFT mode produces the same extraction/matching command arrays, remains the default, and its suite passes unchanged. | command-equality tests + existing scene suite |
| I12-AC-02 | Neural backend is selectable only through validated worker configuration; the API image has no neural dependency and no public contract changes. | Settings validation tests, image inspection, API diff |
| I12-AC-03 | ALIKED + LightGlue builds a COLMAP database through pycolmap 4.2.1's supported import + `verify_matches` path. | actual-binary interoperability test |
| I12-AC-04 | The pinned COLMAP 4.2.1 mapper runs on the neural database and the existing selector inspects the model. | interoperability test (`read_database_stats`, `colmap mapper`, `inspect_model`) |
| I12-AC-05 | Selection and all OpenMVS stages consume the neural result without interface changes. | live neural task through the worker and viewer/download contract |
| I12-AC-06 | Any backend/profile/model/parameter/pairing/resize/verification change invalidates extraction and matching checkpoints. | manifest mismatch tests |
| I12-AC-07 | Configured fallback discards the neural database, rebuilds clean SIFT, and records reason + actual backend. | unit test with injected neural failure + live fallback drill |
| I12-AC-08 | Inference respects device selection, VRAM budget, bounded batches, cancellation and stage timeouts; OOM/CUDA-unavailable paths are stable. | unit tests + live GPU task |
| I12-AC-09 | Unit tests plus the actual-binary interoperability test pass. | suite output |
| I12-AC-10 | A reproducible benchmark compares SIFT exhaustive, SIFT sequential, ALIKED exhaustive, ALIKED sequential and the fast ALIKED profile on identical images/hardware with the Section 10.3 metrics. | benchmark report |
| I12-AC-11 | Neural mode is not the production default; defaults are SIFT with fallback enabled. | `.env` defaults, Settings and SceneConfig tests |
| I12-AC-12 | No descriptors, tensors, absolute paths or command lines leak into diagnostics/metadata. | metadata redaction tests + live result inspection |

## 7. Risks and mitigations

- **Disk space.** The scene image gains a CUDA PyTorch stack (~3–4 GB). Free
  space was 11.8 GB after pruning dangling images; the build reuses cached
  COLMAP/OpenMVS layers. If the export exhausts disk, prune stale build cache
  and rebuild; this is recorded rather than hidden.
- **GPU contention / OOM.** The worker serialises neural stages; explicit
  budget checks and configured fallback prevent a failed task from retrying the
  same OOM configuration.
- **Quality claim.** The benchmark is the only basis for any quality statement;
  no default is changed without it.
