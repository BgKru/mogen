# Object Generation Worker (Phase 5)

TripoSR image-to-3D worker for the mogen application. It runs the real
pretrained model — there is no mock inference path — and plugs into the Phase 4
Celery lifecycle through `app.tasks.object_pipeline`.

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

## Build and run

```powershell
docker compose -f compose.yaml -f compose.gpu.yaml up -d --build object-worker
docker compose logs -f object-worker
docker compose exec object-worker sh -c 'celery -A app.tasks.celery_app:celery_app inspect ping -d celery@$HOSTNAME --timeout 5'
```

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
```

## Licences

TripoSR (MIT), torchmcubes (MPL-2.0), rembg (MIT), PyTorch (BSD-3-Clause),
trimesh (MIT), transformers (Apache-2.0), onnxruntime (MIT), xatlas (MIT).
Retain the upstream notices when redistributing the image.
