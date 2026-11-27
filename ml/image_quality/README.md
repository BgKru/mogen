# Image-quality analysis (`ml/image_quality`)

Implements `docs/additions/11_image_quality_analysis.md` as a shared, advisory,
deterministic analyzer used by both ML pipelines.

```text
ml/image_quality/
├── __init__.py
├── analyzer.py        ImageQualityConfig, analyze_image, analyze_images
├── metrics.py         NumPy/Pillow metric implementations
├── duplicates.py      pHash candidate generation + SSIM confirmation
├── models.py          immutable JSON-compatible result types
├── settings.py        duck-typed adapter from backend Settings
├── pyproject.toml
├── README.md
└── tests/
```

## Dependencies and algorithms

No dependency was added. The analyzer uses only `numpy` and `pillow`, which both
worker images already pin (`numpy==2.3.5`, `pillow==13.0.0`). The Python OpenCV
binding is **not** installed in either image: the scene image has the C++
COLMAP/OpenMVS OpenCV libraries only, and the object image has no OpenCV at all.
Adding `opencv-python` would introduce a second OpenCV/NumPy/FFmpeg family into
both images for six cheap metrics, so the metrics are implemented directly.

| Metric | Algorithm | Unit |
|---|---|---|
| `short_edge` | `min(width, height)` of the decoded image | px |
| `aspect_ratio` | `width / height` | ratio |
| `blur_laplacian_variance` | variance of a 4-neighbour Laplacian on an ITU-R BT.601 grayscale copy normalized to a 512 px long edge (LANCZOS) | 8-bit intensity variance |
| `mean_luminance`, `luminance_std`, `luminance_p05`, `luminance_p95`, `contrast_range` | luminance statistics on a bounded analysis copy (max long edge 1024 px); `contrast_range = p95 - p5` | 8-bit intensity |
| `shadow_clipped_ratio`, `highlight_clipped_ratio` | fraction of analysed pixels `<= 5` and `>= 250` | fraction (0-1) |
| `noise_sigma` | Immerkær high-frequency estimator (`[[1,-2,1],[-2,4,-2],[1,-2,1]]` scaled by `sqrt(pi/2)/6` on a 512 px normalized copy) | 8-bit intensity standard deviation |
| perceptual hash | DCT-II of a 32×32 grayscale copy; low-frequency 8×8 block (DC removed) compared with its median | 63-bit integer |
| SSIM | uniform 8×8 window on a 256×256 grayscale copy; only for pHash candidates | `[-1, 1]` |

The analysis copy is in memory only; it is never saved over the original and no
thumbnail or pixel array is stored in the report. The original bytes and EXIF
metadata are untouched.

## Defaults and calibration

Defaults are **provisional**. They were checked against the repository-owned
photographs in `ml/object_generation/testdata/` and `.proof/sceaux/` (four object
photographs and eleven overlapping scene photographs), not against a broad
consumer-camera corpus. Re-tune for a different camera, resolution regime or
subject class through `IMAGE_QUALITY_*` settings; no code change is needed.

| Setting | Default | Meaning |
|---|---:|---|
| `IMAGE_QUALITY_ENABLED` | `true` | Run analysis; findings are advisory warnings only |
| `IMAGE_QUALITY_REQUIRED` | `false` | When true, an analyzer failure fails the analysis stage instead of being recorded as unavailable |
| `IMAGE_QUALITY_MAX_ANALYSIS_DIMENSION` | `1024` | Long edge bound of the exposure/contrast analysis copy (px) |
| `IMAGE_QUALITY_BLUR_ANALYSIS_EDGE` | `512` | Long edge of the normalized blur/noise copy (px) |
| `IMAGE_QUALITY_MIN_SHORT_EDGE` | `640` | Below this short edge, `LOW_RESOLUTION` (px) |
| `IMAGE_QUALITY_BLUR_THRESHOLD` | `100.0` | Below this Laplacian variance, `LIKELY_BLUR` |
| `IMAGE_QUALITY_UNDEREXPOSURE_THRESHOLD` | `40.0` | Below this mean luminance, `UNDEREXPOSED` |
| `IMAGE_QUALITY_OVEREXPOSURE_THRESHOLD` | `215.0` | Above this mean luminance, `OVEREXPOSED` |
| `IMAGE_QUALITY_SHADOW_CLIP_LEVEL` | `5` | Luminance considered black-clipped |
| `IMAGE_QUALITY_HIGHLIGHT_CLIP_LEVEL` | `250` | Luminance considered white-clipped |
| `IMAGE_QUALITY_CLIPPING_RATIO_THRESHOLD` | `0.15` | Above this clipped fraction, `SHADOW_CLIPPING` / `HIGHLIGHT_CLIPPING` |
| `IMAGE_QUALITY_CONTRAST_THRESHOLD` | `35.0` | Below this p95-p5 range, `LOW_CONTRAST` |
| `IMAGE_QUALITY_NOISE_THRESHOLD` | `15.0` | Above this Immerkær sigma, `HIGH_NOISE` |
| `IMAGE_QUALITY_ASPECT_RATIO_MIN` / `_MAX` | `0.2` / `5.0` | Outside this `width/height` range, `EXTREME_ASPECT_RATIO` |
| `IMAGE_QUALITY_NEAR_DUPLICATE_ENABLED` | `true` | Scene-only pHash candidate detection |
| `IMAGE_QUALITY_NEAR_DUPLICATE_MAX_IMAGES` | `100` | At most this many images are compared (`n*(n-1)/2` pairs) |
| `IMAGE_QUALITY_HASH_DISTANCE_THRESHOLD` | `10` | Hamming distance (of 63 bits) at or below which a pair is a candidate |
| `IMAGE_QUALITY_SSIM_ENABLED` | `true` | Confirm candidates with SSIM |
| `IMAGE_QUALITY_SSIM_THRESHOLD` | `0.92` | Minimum SSIM for a confirmed candidate |

Every finding is a `WARNING`; none of them rejects a photograph. The analyzer
never adds an aggregate quality score and never emits `EXACT_DUPLICATE`, because
byte-identical files are rejected earlier by the SHA-256 dataset validation.

## Pipeline integration

* **Scene reconstruction** analyzes the prepared snapshot inside the
  `IMAGE_PREPARATION` stage (after the dataset copy/validation, before COLMAP
  feature extraction), writes `diagnostics/image_quality.json` in the task
  workspace and attaches the report to `ReconstructionDiagnostics`. Candidate
  near-duplicates are reported; no image is removed and COLMAP still runs.
* **Object generation** analyzes the decoded original photograph before
  TripoSR preprocessing. The report is added to `run.json` and to the
  generated asset metadata under `image_quality`.

Advisory failure records `QUALITY_ANALYSIS_UNAVAILABLE`; required failure raises
`QUALITY_ANALYSIS_FAILED` for the analysis stage only.

## Tests and runtime

```bash
# Scene worker image (also has Pillow/NumPy)
docker run --rm -v "${PWD}/ml:/work/ml" -w /work/ml/image_quality \
  -e PYTHONPATH=/work/ml:/app mogen-scene-worker:dev python -m pytest -q

# Object worker image
docker run --rm -v "${PWD}/ml:/work/ml" -w /work/ml/image_quality \
  -e PYTHONPATH=/work/ml:/app mogen-object-worker:dev python -m pytest -q
```

The tests synthesize images with Pillow/NumPy; no dataset download is required.
Measured analysis cost on the eleven-photograph Sceaux set and the largest
100-image bounded comparison is reported in the implementation note in
`docs/additions/11_image_quality_analysis.md` (Section 13).
