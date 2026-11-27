# Object Generation Worker (Phase 5, increment 13)

Single-image image-to-3D worker for the mogen application. TripoSR is the
default generator and the regression baseline. Post-MVP increment 13 adds
Stable Fast 3D as an opt-in alternative behind a small generator contract; the
same Celery lifecycle, result contract, viewer and download path are used. There
is no mock inference path.

## Pinned versions

| Component | Pin | Source |
|---|---|---|
| TripoSR source | commit `d26e33181947bbbc4c6fc0f5734e1ec6c080956e` | `https://github.com/VAST-AI-Research/TripoSR` (MIT) |
| TripoSR weights | revision `5b521936b01fbe1890f6f9baed0254ab6351c04a` | `stabilityai/TripoSR` (MIT) |
| `model.ckpt` | SHA-256 `429e2c6b22a0923967459de24d67f05962b235f79cde6b032aa7ed2ffcd970ee` (1 677 246 742 bytes) | Hugging Face |
| DINO config | `facebook/dino-vitb16` revision `f205d5d8e640a89a2b8ef0369670dfc37cc07fc2` | Hugging Face |
| PyTorch runtime | `pytorch/pytorch:2.14.1-cuda12.6-cudnn9-runtime` (torch 2.14.1+cu126) | Docker Hub (BSD-3-Clause) |
| PyTorch build | `pytorch/pytorch:2.14.1-cuda12.6-cudnn9-devel` | Docker Hub (BSD-3-Clause) |
| `torchmcubes` | commit `a9ac95aa329957ba646e7bb057f825f5dfa77f38` | `tatsy/torchmcubes` (MPL-2.0) |
| SF3D source (increment 13) | commit `ff21fc491b4dc5314bf6734c7c0dabd86b5f5bb2` | `Stability-AI/stable-fast-3d` (Stability AI Community License) |
| SF3D weights (increment 13) | revision `f0c9a8ffd62cb1bbc8a7a53c9f87a0be1b6be778` (`config.yaml` + `model.safetensors`, 3.84 GB) | `stabilityai/stable-fast-3d`, gated |
| Python | 3.12.3 (the pinned PyTorch image runtime) | — |
| CUDA | 12.6 (host driver 617.42) | — |
| GPU tested | NVIDIA GeForce RTX 3060, 12 GB | — |

The backend API image remains Python 3.11. The worker image ships Python 3.12.3
because that is the runtime bundled with the pinned PyTorch 2.14.1 image; the
application code keeps a Python 3.11 language target and the API suite runs on
3.11. This deviation from `phase0_decisions.md`'s "3.11.x" line is recorded in
the Phase 5 close-out review.

`torchmcubes` is compiled once in the devel stage against the exact torch/CUDA
pair with `CMAKE_CUDA_ARCHITECTURES=86` (Ampere; RTX 3060) and installed from
the resulting wheel in the runtime stage. It is not compiled during deployment.

## Model cache

The `triposr_model_cache` Compose volume mounts at `/models` and contains:

```text
/models/
├── triposr/config.yaml
├── triposr/model.ckpt
├── hf/hub/models--facebook--dino-vitb16/...
├── u2net/u2net.onnx
└── model-manifest.json
```

The `model-init` Compose service populates and verifies the cache before the
worker starts. The worker runs with `HF_HUB_OFFLINE=1`; a generation task never
downloads anything.

Increment 13 adds a second, separate cache entry for the opt-in SF3D worker:

```text
/models/sf3d/
├── config.yaml
├── model.safetensors
├── LICENSE.md
└── model-manifest.json        # model_id, pinned revision, per-file SHA-256
```

`sf3d-model-init` (defined only in `compose.sf3d.yaml`) populates it with
`python -m object_generation.sf3d.download_models`. The SF3D repository is
gated: the initializer needs a Hugging Face read token (`HF_TOKEN`) whose
account has accepted the Stability AI Community License. The token is used only
by the initializer and is never logged or written to the result metadata.
`SF3DAdapter.load()` re-verifies every file against the manifest before the
worker accepts a task.

The initializer also seeds the two public auxiliary models SF3D instantiates at
load time — `facebook/dinov2-large` and open_clip `ViT-B-32` /
`laion2b_s34b_b79k` — into the `HF_HOME` cache (`/models/hf`), retrying
`local_files_only` when the host is offline, and records them under the
manifest's `auxiliary` key. Without them the offline worker fails with
`LocalEntryNotFoundError` on its first task. The verified cache was populated on
2026-11-26; the real tests (2/2), the live task and the benchmark are recorded in
`docs/reviews/increment13_closeout.md` Section 8.

```powershell
docker compose logs -f object-worker
docker compose exec object-worker sh -c 'celery -A app.tasks.celery_app:celery_app inspect ping -d celery@$HOSTNAME --timeout 5'
```

## Generators (increment 13)

| Generator | Selection | Preprocessing | Appearance |
|---|---|---|---|
| TripoSR (default) | `OBJECT_GENERATOR=triposr` | rembg, crop, ratio, 512 px neutral composite | vertex colours |
| Stable Fast 3D (opt-in) | `OBJECT_GENERATOR=sf3d` + `OBJECT_SF3D_ENABLED=true` | rembg, crop, ratio, RGBA (SF3D resizes internally) | UVs + PBR base-colour/normal textures |

Rules enforced by the code:

- one generator per worker process, selected at startup; unknown or disabled
  names fail configuration validation;
- `OBJECT_GENERATOR_FALLBACK=true` allows a **pre-inference** fallback to
  TripoSR, recorded as `generator.fallback` with the reason; a failure after
  inference starts is a task error;
- background removal and foreground resizing run exactly once for both
  generators;
- result metadata gains a `generator` object with the adapter name, pinned
  source revision, model id/revision, timings, `preprocessing_profile`, measured
  peak CUDA bytes when available, and the SF3D texture resolution/remesh mode;
- model caches are separate and offline at task time.

Hunyuan3D is **not available** in this build: the published licence excludes
the EU, UK and South Korea, the shape stage is reported at ~10 GB VRAM on a 12 GB
card, and its PyTorch 2.5.1/CUDA 12.4 stack conflicts with the pinned runtime.
The settings still validate and refuse to initialise it with a stable message.

## Mesh/texture enhancement (increment 14)

Enhancement runs between the generator's normalized output and the existing GLB
export. It never changes the generator, preprocessing, task stages, result
contract or viewer.

| Operation | Default | Notes |
|---|---|---|
| Conservative cleanup | on | removes repeated-index/zero-area faces and unreferenced vertices; merges duplicate vertices only within a scale-aware tolerance and never across UV seams; no hole filling or smoothing |
| Normal validation/correction | on | area-weighted NumPy normals; winding correction only for a watertight single component; `NORMAL` is exported only when this stage ran |
| Simplification | off | guarded by target faces, attribute preservation and sampled deviation; no quadric simplifier is pinned, so the production path safely skips with `SIMPLIFIER_UNAVAILABLE` |
| xatlas UV generation | off | runs only when baking needs an atlas or `OBJECT_GENERATE_UV=true`; existing valid UVs are preserved |
| Vertex-colour baking | off | xatlas unwrap + deterministic CPU rasteriser + embedded base-colour texture and PBR material; a generator-provided texture is preserved, not rebaked |
| AI texture | off/unavailable | protocol, lazy factory and output validation exist; no model passed the licence, compatibility, cache and RTX 3060 review, so enabling it fails validation |

The shared pure utilities live in `ml/mesh_enhancement/` and are installed in
both worker images. `OBJECT_MESH_MERGE_TOLERANCE` is a fraction of the bounding
box diagonal. `enhancement_fallback_to_original=true` keeps the last validated
asset when an optional operation fails; source-geometry validation never falls
back. Result metadata and `run.json` gain a compact `enhancement` block with
operations, before/after counts, UV/texture/normal flags, skips, fallback,
timings, peak RSS and the enhancement manifest. No paths, tensors or image
buffers are published.

Measured on the retained real TripoSR GLB (38 241 vertices / 76 315 faces) with
three repetitions at a 512 px atlas: baseline 0.64 s, cleanup+normals 0.83 s,
baked 38.1 s (xatlas unwrap dominates; the vectorised bake itself is <1 s). The
baked GLB is 3.21 MB, has 0 Khronos errors/warnings and `hasTextures=true`. See
`docs/reviews/increment14_closeout.md`.

## Build and run

```powershell
# Default: TripoSR
docker compose -f compose.yaml -f compose.gpu.yaml up -d --build object-worker

# Opt-in: Stable Fast 3D (replaces the single object_generation worker policy)
$env:HF_TOKEN = "<read token for the gated repository>"
docker compose -f compose.yaml -f compose.gpu.yaml -f compose.sf3d.yaml up -d --build object-worker sf3d-model-init
```

The SF3D target is large: it pulls the PyTorch devel image (~10 GB) to compile
`texture_baker` and `uv_unwrapper` and adds the isolated dependency directory
`/opt/sf3d-site`. The default image and its dependency set are unchanged. The
native build passes `USE_CUDA=1`; upstream `setup.py` otherwise derives `USE_CUDA`
from `torch.cuda.is_available()`, which is false in the GPU-less builder and
produces a wheel with CPU-only kernels (fixed 2026-11-26). A rebuild is required
for the canonical `mogen-object-worker:sf3d`; the verified interim image is
`mogen-object-worker:sf3d-cuda`.

Without the GPU override the worker uses `OBJECT_ALLOW_CPU_FALLBACK` as
configured; CPU is never selected silently.

## Standalone proof (roadmap 5.2)

```powershell
docker run --rm --gpus all `
  -v mogen_triposr_model_cache:/models `
  -v "${PWD}/ml:/work/ml" `
  -v "H:/Study/mogen-model-cache/proof:/proof" `
  -w /work/ml/object_generation `
  -e PYTHONPATH=/work/ml:/opt/triposr:/opt `
  mogen-object-worker:dev `
  python -m object_generation.standalone `
    --image /work/ml/object_generation/testdata/car-1.jpg `
    --output-dir /proof --model-dir /models/triposr
```

Then verify the exported file with the same Three.js GLTFLoader used by the
viewer and the Khronos glTF Validator:

```powershell
cd ml/object_generation/viewer
npm install
node load_glb.mjs H:/Study/mogen-model-cache/proof/output/model.glb
```

The result is validated twice: by the pipeline's independent GLB parser and
again through Three.js/`gltf-validator` in the viewer check.

Before preprocessing, the pipeline runs the shared advisory analyzer from
`ml/image_quality/` on the decoded original photograph. Its report is added to
the task's `run.json` and to the generated asset metadata under
`image_quality`; it never changes the image passed to TripoSR
(see `docs/additions/11_image_quality_analysis.md`).

## Tests

```powershell
# Unit tests (no model weights required)
docker run --rm -v "${PWD}/ml:/work/ml" -w /work/ml/object_generation `
  -e PYTHONPATH=/work/ml:/opt/triposr:/opt `
  mogen-object-worker:dev python -m pytest -q

# Real inference (TEST-AC-12); requires the GPU override and the model cache
docker run --rm --gpus all -v mogen_triposr_model_cache:/models `
  -v "${PWD}/ml:/work/ml" -w /work/ml/object_generation `
  -e PYTHONPATH=/work/ml:/opt/triposr:/opt `
  -e RUN_REAL_MODEL_TESTS=1 mogen-object-worker:dev `
  python -m pytest -m real_model

# Real Stable Fast 3D inference (increment 13); needs the SF3D cache and the
# CUDA-enabled image (the canonical :sf3d target still needs a USE_CUDA=1 rebuild)
docker run --rm --gpus all -v mogen_triposr_model_cache:/models `
  -v "${PWD}/ml:/work/ml" -w /work/ml/object_generation `
  -e PYTHONPATH=/work/ml:/opt/sf3d-site:/opt/sf3d-src:/opt/triposr:/opt `
  -e RUN_SF3D_REAL_TESTS=1 -e SF3D_TEST_DEVICE=cuda:0 `
  -e HF_HUB_OFFLINE=1 -e TRANSFORMERS_OFFLINE=1 mogen-object-worker:sf3d-cuda `
  python -m pytest -m real_sf3d
```

## Benchmark (increment 13)

```powershell
docker run --rm --gpus all -v mogen_triposr_model_cache:/models `
  -v "${PWD}/ml:/work/ml" -v "${PWD}/.proof/increment13/benchmark:/proof" `
  -e PYTHONPATH=/work/ml:/opt/sf3d-site:/opt/sf3d-src:/app:/opt/triposr:/opt `
  -e HF_HUB_OFFLINE=1 -e TRANSFORMERS_OFFLINE=1 `
  mogen-object-worker:sf3d-cuda python -m object_generation.benchmarks.run_benchmark `
  --images /work/ml/object_generation/testdata --generators triposr,sf3d `
  --repetitions 3 --device cuda:0 --output /proof/sf3d-benchmark.json
```

The benchmark runs one warm-up plus N measured repetitions per image and reports
median/p95 latency, failure rate, peak CUDA bytes, file size and mesh counts. It
uses the same pipeline entry point as production and never fabricates a result
for an unavailable generator.

## Licences

TripoSR (MIT), torchmcubes (MPL-2.0), rembg (MIT), PyTorch (BSD-3-Clause),
trimesh (MIT), transformers (Apache-2.0), onnxruntime (MIT), xatlas (MIT).

Stable Fast 3D (source and weights) is distributed under the Stability AI
Community License and the weights are gated on Hugging Face. Review the licence
before redistribution or hosted commercial use and retain the upstream notices.
The extra dependency set (open_clip_torch, timm, gpytoolbox, scs,
scikit-image, pynanoinstantmeshes, jaxtyping, ftfy, regex, sentencepiece,
protobuf) keeps its own licences in `/opt/sf3d-site`; they are installed only in
the SF3D image target.
