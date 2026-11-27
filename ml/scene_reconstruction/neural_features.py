"""ALIKED + LightGlue neural feature backend (12_advanced_feature_matching.md).

The adapter runs inside the scene worker only. It extracts ALIKED-N16 features,
matches them with LightGlue, imports keypoints/matches into a COLMAP 4.2.1
database through pycolmap 4.2.1's supported API and runs pycolmap's geometric
verification. Every intermediate database is task-local and replaced atomically;
a failure never leaves a half-imported database eligible for checkpoint reuse.

Heavy modules (torch, torchvision, kornia, lightglue, pycolmap) are imported
lazily so the default SIFT path never loads them.
"""

from __future__ import annotations

import gc
import hashlib
import logging
import math
import os
import shutil
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from PIL import Image

from .colmap_runner import ColmapRunner, read_database_stats
from .config import SceneConfig
from .dataset import SceneDataset
from .exceptions import (
    COLMAP_DATABASE_INCOMPATIBLE,
    FEATURE_EXTRACTION_FAILED,
    INSUFFICIENT_FEATURES,
    NEURAL_CUDA_UNAVAILABLE,
    NEURAL_FEATURE_EXTRACTION_FAILED,
    NEURAL_MATCHING_FAILED,
    NEURAL_MODEL_UNAVAILABLE,
    NEURAL_RESOURCE_EXHAUSTED,
    NEURAL_RUNTIME_UNAVAILABLE,
    NEURAL_VERIFICATION_FAILED,
    NO_VALID_MATCHES,
    FeatureMatchError,
    ResourceError,
    ToolError,
)
from .feature_matching import (
    FeatureExtractionResult,
    FeatureMatchingResult,
    RuntimeInfo,
    features_path,
    generate_pairs,
)
from .feature_profiles import (
    ALIKED_DESCRIPTOR_DIM,
    ALIKED_MODEL_NAME,
    ALIKED_WEIGHTS_FILENAME,
    ALIKED_WEIGHTS_SHA256,
    BACKEND_ALIKED_LIGHTGLUE,
    LIGHTGLUE_FEATURES,
    LIGHTGLUE_REVISION,
    LIGHTGLUE_WEIGHTS_FILENAME,
    LIGHTGLUE_WEIGHTS_SHA256,
    VERIFICATION_MAX_TRIALS,
    VERIFICATION_MIN_INLIER_RATIO,
)

logger = logging.getLogger(__name__)

MIN_KEYPOINTS_PER_IMAGE = 16
MIN_FREE_VRAM_MB = 2048
_CHUNK_MB = 1024 * 1024


@dataclass(frozen=True, slots=True)
class NeuralVersions:
    """Installed neural runtime versions, recorded in diagnostics only."""

    torch: str
    torchvision: str
    kornia: str
    pycolmap: str
    lightglue: str

    def as_dict(self) -> dict[str, str]:
        return {
            "torch": self.torch,
            "torchvision": self.torchvision,
            "kornia": self.kornia,
            "pycolmap": self.pycolmap,
            "lightglue": self.lightglue,
        }


def _torch_home() -> Path:
    configured = os.environ.get("TORCH_HOME", "").strip()
    if configured:
        return Path(configured)
    return Path.home() / ".cache" / "torch"


def model_cache_path(filename: str) -> Path:
    """Return the baked checkpoint path used by ``torch.hub``."""
    return _torch_home() / "hub" / "checkpoints" / filename


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(_CHUNK_MB):
            digest.update(chunk)
    return digest.hexdigest()


def verify_model_files() -> dict[str, str]:
    """Verify both pinned checkpoints and return their paths.

    Missing or modified weights fail with a stable model error instead of
    silently downloading a different checkpoint at task time.
    """
    expected = {
        ALIKED_WEIGHTS_FILENAME: ALIKED_WEIGHTS_SHA256,
        LIGHTGLUE_WEIGHTS_FILENAME: LIGHTGLUE_WEIGHTS_SHA256,
    }
    verified: dict[str, str] = {}
    for filename, checksum in expected.items():
        path = model_cache_path(filename)
        if not path.is_file():
            raise ToolError(
                NEURAL_MODEL_UNAVAILABLE,
                "The neural feature models are not installed in this worker.",
            )
        if _sha256(path) != checksum:
            raise ToolError(
                NEURAL_MODEL_UNAVAILABLE,
                "The neural feature models failed their integrity check.",
            )
        verified[filename] = str(path)
    return verified


def _import_runtime():
    try:
        import kornia  # noqa: F401 - version probe
        import pycolmap
        import torch
        import torchvision
        from lightglue import ALIKED, LightGlue
    except Exception as exc:  # noqa: BLE001 - any import failure is unavailable
        raise ToolError(
            NEURAL_RUNTIME_UNAVAILABLE,
            "The neural feature runtime is unavailable in this worker.",
        ) from exc
    return torch, torchvision, kornia, pycolmap, ALIKED, LightGlue


def runtime_versions() -> NeuralVersions:
    torch, torchvision, kornia, pycolmap, _, _ = _import_runtime()
    return NeuralVersions(
        torch=str(torch.__version__),
        torchvision=str(torchvision.__version__),
        kornia=str(kornia.__version__),
        pycolmap=str(pycolmap.__version__),
        lightglue=f"LightGlue@{LIGHTGLUE_REVISION}",
    )


def resize_scale(width: int, height: int, max_edge: int) -> float:
    """Return the scale applied before inference (never upscales)."""
    if width < 1 or height < 1:
        raise FeatureMatchError(
            FEATURE_EXTRACTION_FAILED, "A prepared image has invalid dimensions."
        )
    return min(1.0, float(max_edge) / float(max(width, height)))


def _restore_with_mask(
    keypoints: np.ndarray, *, scale: float, width: int, height: int
) -> tuple[np.ndarray, np.ndarray]:
    """Return restored keypoints and the mask of detections inside the image."""
    points = np.asarray(keypoints, dtype=np.float32).reshape(-1, 2)
    if scale <= 0 or not math.isfinite(scale):
        raise FeatureMatchError(
            FEATURE_EXTRACTION_FAILED, "The feature scale transform is invalid."
        )
    restored = (points + 0.5) / scale - 0.5
    mask = (
        np.isfinite(restored).all(axis=1)
        & (restored[:, 0] >= 0)
        & (restored[:, 1] >= 0)
        & (restored[:, 0] <= width - 1)
        & (restored[:, 1] <= height - 1)
    )
    return restored[mask], mask


def restore_keypoints(
    keypoints: np.ndarray, *, scale: float, width: int, height: int
) -> np.ndarray:
    """Map resized-image keypoints back to original pixel coordinates.

    ALIKED returns coordinates in the (possibly resized) inference image. The
    stored value must be in the original image coordinate system expected by the
    COLMAP import layer. Detections that fall outside the image are dropped.
    """
    restored, _ = _restore_with_mask(keypoints, scale=scale, width=width, height=height)
    return restored


def validate_features(keypoints: np.ndarray, descriptors: np.ndarray, *, expected_dim: int) -> None:
    """Reject malformed, non-finite or wrongly shaped feature arrays."""
    points = np.asarray(keypoints)
    desc = np.asarray(descriptors)
    if points.ndim != 2 or points.shape[1] != 2:
        raise FeatureMatchError(
            NEURAL_FEATURE_EXTRACTION_FAILED, "The extracted keypoints are malformed."
        )
    if desc.ndim != 2 or desc.shape[1] != expected_dim or desc.shape[0] != points.shape[0]:
        raise FeatureMatchError(
            NEURAL_FEATURE_EXTRACTION_FAILED, "The extracted descriptors are malformed."
        )
    if points.shape[0] < MIN_KEYPOINTS_PER_IMAGE:
        raise FeatureMatchError(
            INSUFFICIENT_FEATURES, "A photograph produced too few usable features."
        )
    if not np.isfinite(points).all() or not np.isfinite(desc).all():
        raise FeatureMatchError(
            NEURAL_FEATURE_EXTRACTION_FAILED, "The extracted features are not finite."
        )


def _device_for(config: SceneConfig, torch) -> str:
    requested = config.feature_device
    if requested == "cpu":
        return "cpu"
    available = bool(torch.cuda.is_available())
    if requested == "cuda" and not available:
        raise ResourceError(
            NEURAL_CUDA_UNAVAILABLE, "CUDA was requested but is not available in this worker."
        )
    return "cuda" if available else "cpu"


def _check_memory(device: str, config: SceneConfig, torch) -> None:
    if device != "cuda":
        return
    free_bytes, _ = torch.cuda.mem_get_info()
    free_mb = free_bytes / (1024 * 1024)
    if free_mb < MIN_FREE_VRAM_MB:
        raise ResourceError(
            NEURAL_RESOURCE_EXHAUSTED, "The GPU does not have enough free memory for this stage."
        )
    if free_mb < config.feature_max_vram_mb:
        logger.warning(
            "neural_vram_below_budget",
            extra={
                "operation": "scene_reconstruction",
                "free_vram_mb": round(free_mb, 1),
                "budget_vram_mb": config.feature_max_vram_mb,
            },
        )


def _peak_vram_mb(device: str, torch) -> float | None:
    if device != "cuda":
        return None
    return float(torch.cuda.max_memory_allocated()) / (1024 * 1024)


def _release(torch) -> None:
    gc.collect()
    if hasattr(torch, "cuda") and torch.cuda.is_available():
        torch.cuda.empty_cache()
        torch.cuda.synchronize()


def _is_oom(exc: BaseException) -> bool:
    text = str(exc).lower()
    return isinstance(exc, MemoryError) or (
        "out of memory" in text or "cuda error" in text and "memory" in text
    )


def _as_resource_error(exc: BaseException) -> ResourceError:
    return ResourceError(
        NEURAL_RESOURCE_EXHAUSTED,
        "The neural feature stage ran out of memory.",
    )


class AlikedLightGlueBackend:
    """ALIKED extraction + LightGlue matching + pycolmap import/verification."""

    name = BACKEND_ALIKED_LIGHTGLUE

    def __init__(self, config: SceneConfig, *, colmap: ColmapRunner | None = None) -> None:
        self._config = config
        self._colmap = colmap
        self._profile = config.resolved_feature_profile
        self._device: str | None = None
        self._versions: NeuralVersions | None = None

    # -- runtime ---------------------------------------------------------

    def verify_runtime(self, config: SceneConfig) -> RuntimeInfo:
        versions = runtime_versions()
        torch, *_ = _import_runtime()
        verify_model_files()
        device = _device_for(config, torch)
        self._versions = versions
        return RuntimeInfo(
            backend=self.name,
            available=True,
            device=device,
            versions=versions.as_dict(),
        )

    def _load(self, *, extractor_only: bool):
        torch, _, _, _, ALIKED, LightGlue = _import_runtime()
        verify_model_files()
        device = _device_for(self._config, torch)
        self._device = device
        _check_memory(device, self._config, torch)
        torch.manual_seed(0)
        np.random.seed(0)
        try:
            extractor = (
                ALIKED(
                    model_name=ALIKED_MODEL_NAME,
                    max_num_keypoints=self._config.effective_max_keypoints(),
                    detection_threshold=self._profile.detection_threshold,
                    nms_radius=self._profile.nms_radius,
                )
                .eval()
                .to(device)
            )
            matcher = None
            if not extractor_only:
                matcher = (
                    LightGlue(
                        features=LIGHTGLUE_FEATURES,
                        depth_confidence=self._profile.depth_confidence,
                        width_confidence=self._profile.width_confidence,
                        filter_threshold=self._config.feature_match_threshold,
                    )
                    .eval()
                    .to(device)
                )
        except Exception as exc:  # noqa: BLE001 - map model/OOM failures
            if _is_oom(exc):
                raise _as_resource_error(exc) from exc
            raise ToolError(
                NEURAL_MODEL_UNAVAILABLE,
                "The neural feature models could not be loaded.",
            ) from exc
        if device == "cuda":
            torch.cuda.reset_peak_memory_stats()
        return torch, extractor, matcher, device

    # -- extraction ------------------------------------------------------

    def _analyze_image(self, torch, extractor, image, device) -> tuple[np.ndarray, np.ndarray]:
        scale = resize_scale(image.width, image.height, self._config.feature_image_max_size)
        working = image
        if scale < 1.0:
            working = image.resize(
                (max(1, round(image.width * scale)), max(1, round(image.height * scale))),
                Image.Resampling.LANCZOS,
            )
        array = np.asarray(working.convert("RGB"), dtype=np.float32) / 255.0
        tensor = torch.from_numpy(array.transpose(2, 0, 1)).unsqueeze(0).to(device)
        try:
            with torch.inference_mode():
                output = extractor({"image": tensor})
        except Exception as exc:  # noqa: BLE001 - map runtime failures
            if _is_oom(exc):
                raise _as_resource_error(exc) from exc
            raise ToolError(
                NEURAL_FEATURE_EXTRACTION_FAILED,
                "Neural feature extraction failed for a photograph.",
            ) from exc
        finally:
            del tensor
        keypoints = output["keypoints"][0].detach().float().cpu().numpy()
        descriptors = output["descriptors"][0].detach().float().cpu().numpy()
        restored, mask = _restore_with_mask(
            keypoints, scale=scale, width=image.width, height=image.height
        )
        descriptors = np.asarray(descriptors, dtype=np.float32)[mask]
        validate_features(restored, descriptors, expected_dim=ALIKED_DESCRIPTOR_DIM)
        return restored, descriptors

    def extract_features(
        self,
        dataset: SceneDataset,
        *,
        images_dir: Path,
        database_path: Path,
        work_dir: Path,
        on_poll: Callable[[], None],
    ) -> FeatureExtractionResult:
        started = time.monotonic()
        torch, extractor, _, device = self._load(extractor_only=True)
        arrays: dict[str, np.ndarray] = {"names": np.array([i.filename for i in dataset.images])}
        counts: list[int] = []
        try:
            for index, prepared in enumerate(dataset.images):
                on_poll()
                with Image.open(prepared.path) as opened:
                    opened.load()
                    image = opened.convert("RGB")
                keypoints, descriptors = self._analyze_image(torch, extractor, image, device)
                arrays[f"kp_{index}"] = keypoints
                arrays[f"desc_{index}"] = descriptors
                arrays[f"size_{index}"] = np.array([image.width, image.height], dtype=np.int64)
                counts.append(int(keypoints.shape[0]))
                on_poll()
            self._write_feature_file(features_path(database_path.parent), arrays)
            self._import_database(dataset, images_dir, database_path, arrays)
        finally:
            del extractor
            _release(torch)
        peak = _peak_vram_mb(device, torch)
        seconds = time.monotonic() - started
        logger.info(
            "neural_features_extracted",
            extra={
                "operation": "scene_reconstruction",
                "images": len(counts),
                "keypoints_total": int(sum(counts)),
                "device": device,
                "seconds": round(seconds, 3),
            },
        )
        return FeatureExtractionResult(
            backend=self.name,
            profile=self._profile.name,
            images=len(counts),
            keypoints_total=int(sum(counts)),
            keypoints_min=int(min(counts)) if counts else 0,
            keypoints_max=int(max(counts)) if counts else 0,
            seconds=seconds,
            device=device,
            precision="fp32",
            peak_vram_mb=peak,
        )

    def _write_feature_file(self, path: Path, arrays: dict[str, np.ndarray]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(f"{path.name}.tmp")
        with temporary.open("wb") as stream:
            np.savez(stream, **arrays)
        os.replace(temporary, path)

    def _import_database(
        self,
        dataset: SceneDataset,
        images_dir: Path,
        database_path: Path,
        arrays: dict[str, np.ndarray],
    ) -> None:
        _, _, _, pycolmap, _, _ = _import_runtime()
        temporary = database_path.with_suffix(".db.tmp")
        temporary.unlink(missing_ok=True)
        names = [prepared.filename for prepared in dataset.images]
        try:
            with pycolmap.Database.open(temporary):
                pass
            options = pycolmap.ImageReaderOptions()
            try:
                options.camera_model = self._config.colmap_camera_model
            except (AttributeError, TypeError):  # pragma: no cover - pycolmap struct
                logger.warning(
                    "neural_reader_options_default",
                    extra={"operation": "scene_reconstruction"},
                )
            pycolmap.import_images(
                temporary,
                Path(images_dir),
                pycolmap.CameraMode.AUTO,
                image_names=names,
                options=options,
            )
            with pycolmap.Database.open(temporary) as database:
                image_ids = {image.name: image.image_id for image in database.read_all_images()}
                if set(image_ids) != set(names):
                    raise FeatureMatchError(
                        COLMAP_DATABASE_INCOMPATIBLE,
                        "COLMAP did not register every prepared photograph.",
                    )
                for index, name in enumerate(names):
                    keypoints = np.asarray(arrays[f"kp_{index}"], dtype=np.float32)
                    database.write_keypoints(image_ids[name], keypoints + 0.5)
            stats = read_database_stats(temporary)
            if stats.images != dataset.image_count or stats.keypoints <= 0:
                raise FeatureMatchError(
                    COLMAP_DATABASE_INCOMPATIBLE,
                    "The neural feature database is incomplete.",
                )
            os.replace(temporary, database_path)
        except FeatureMatchError:
            temporary.unlink(missing_ok=True)
            raise
        except Exception as exc:  # noqa: BLE001 - pycolmap/sqlite failures
            temporary.unlink(missing_ok=True)
            raise FeatureMatchError(
                COLMAP_DATABASE_INCOMPATIBLE,
                "The neural features could not be imported into the COLMAP database.",
            ) from exc

    # -- matching --------------------------------------------------------

    def _load_features(
        self, path: Path, names: list[str]
    ) -> dict[str, tuple[np.ndarray, np.ndarray]]:
        try:
            with np.load(path) as archive:
                stored_names = [str(name) for name in archive["names"].tolist()]
                if stored_names != names:
                    raise FeatureMatchError(
                        NEURAL_MATCHING_FAILED,
                        "The neural features do not match the prepared dataset.",
                    )
                features: dict[str, tuple[np.ndarray, np.ndarray]] = {}
                for index, name in enumerate(names):
                    keypoints = np.asarray(archive[f"kp_{index}"], dtype=np.float32)
                    descriptors = np.asarray(archive[f"desc_{index}"], dtype=np.float32)
                    features[name] = (keypoints, descriptors)
        except FeatureMatchError:
            raise
        except (OSError, ValueError) as exc:
            raise FeatureMatchError(
                NEURAL_MATCHING_FAILED, "The extracted neural features are not readable."
            ) from exc
        return features

    def match_features(
        self,
        dataset: SceneDataset,
        *,
        images_dir: Path,
        database_path: Path,
        work_dir: Path,
        on_poll: Callable[[], None],
    ) -> FeatureMatchingResult:
        started = time.monotonic()
        names = [prepared.filename for prepared in dataset.images]
        pairs = generate_pairs(
            names,
            strategy=self._config.feature_pair_strategy,
            sequential_overlap=self._config.feature_sequential_overlap,
            max_pairs=self._config.feature_max_pairs,
        )
        raw_features = self._load_features(features_path(database_path.parent), names)
        _, _, _, pycolmap, _, _ = _import_runtime()
        torch, _, matcher, device = self._load(extractor_only=False)
        temporary = database_path.with_suffix(".db.tmp")
        temporary.unlink(missing_ok=True)
        shutil.copy2(database_path, temporary)
        pairs_path = Path(work_dir) / "colmap" / "pairs.txt"
        pairs_path.parent.mkdir(parents=True, exist_ok=True)
        pairs_path.write_text("".join(f"{a} {b}\n" for a, b in pairs), encoding="utf-8")
        matched_pairs = 0
        stats = None
        sizes = {
            prepared.filename: (prepared.width, prepared.height) for prepared in dataset.images
        }
        try:
            with pycolmap.Database.open(temporary) as database:
                image_ids = {image.name: image.image_id for image in database.read_all_images()}
                for left, right in pairs:
                    on_poll()
                    left_kp, left_desc = raw_features[left]
                    right_kp, right_desc = raw_features[right]
                    matches = self._match_pair(
                        torch,
                        matcher,
                        left_kp,
                        left_desc,
                        right_kp,
                        right_desc,
                        sizes[left],
                        sizes[right],
                        device,
                    )
                    if len(matches) >= self._config.feature_min_matches:
                        database.write_matches(
                            image_ids[left], image_ids[right], matches.astype(np.int32)
                        )
                        matched_pairs += 1
                    on_poll()
            self._verify(pycolmap, temporary, pairs_path)
            stats = read_database_stats(temporary)
            if stats.verified_pairs <= 0 or stats.largest_component < 2:
                raise FeatureMatchError(
                    NO_VALID_MATCHES,
                    "The photographs have no geometrically verified neural matches.",
                )
            os.replace(temporary, database_path)
        except FeatureMatchError:
            temporary.unlink(missing_ok=True)
            raise
        except Exception as exc:  # noqa: BLE001 - pycolmap/verification failures
            temporary.unlink(missing_ok=True)
            if _is_oom(exc):
                raise _as_resource_error(exc) from exc
            raise FeatureMatchError(
                NEURAL_VERIFICATION_FAILED,
                "The neural matches could not be geometrically verified.",
            ) from exc
        finally:
            del matcher
            _release(torch)
        peak = _peak_vram_mb(device, torch)
        seconds = time.monotonic() - started
        logger.info(
            "neural_features_matched",
            extra={
                "operation": "scene_reconstruction",
                "pairs": len(pairs),
                "matched_pairs": matched_pairs,
                "verified_pairs": stats.verified_pairs,
                "device": device,
                "seconds": round(seconds, 3),
            },
        )
        return FeatureMatchingResult(
            backend=self.name,
            profile=self._profile.name,
            strategy=self._config.feature_pair_strategy,
            pairs=len(pairs),
            pairs_with_matches=matched_pairs,
            verified_pairs=stats.verified_pairs,
            seconds=seconds,
            device=device,
            precision="fp32",
            peak_vram_mb=peak,
        )

    def _match_pair(
        self,
        torch,
        matcher,
        left_kp: np.ndarray,
        left_desc: np.ndarray,
        right_kp: np.ndarray,
        right_desc: np.ndarray,
        left_size: tuple[int, int],
        right_size: tuple[int, int],
        device: str,
    ) -> np.ndarray:
        data = {
            "image0": {
                "keypoints": torch.from_numpy(left_kp[None]).to(device),
                "descriptors": torch.from_numpy(left_desc[None]).to(device),
                "image_size": torch.tensor([[left_size[0], left_size[1]]], device=device),
            },
            "image1": {
                "keypoints": torch.from_numpy(right_kp[None]).to(device),
                "descriptors": torch.from_numpy(right_desc[None]).to(device),
                "image_size": torch.tensor([[right_size[0], right_size[1]]], device=device),
            },
        }
        try:
            with torch.inference_mode():
                result = matcher(data)
        except Exception as exc:  # noqa: BLE001 - map matching failures
            if _is_oom(exc):
                raise _as_resource_error(exc) from exc
            raise FeatureMatchError(
                NEURAL_MATCHING_FAILED, "Neural feature matching failed for an image pair."
            ) from exc
        matches = result["matches"][0].detach().cpu().numpy()
        if matches.size == 0:
            return np.zeros((0, 2), dtype=np.int32)
        return matches.astype(np.int32)

    def _verify(self, pycolmap, database_path: Path, pairs_path: Path) -> None:
        try:
            pycolmap.verify_matches(
                database_path,
                pairs_path,
                options=dict(
                    ransac=dict(
                        max_num_trials=VERIFICATION_MAX_TRIALS,
                        min_inlier_ratio=VERIFICATION_MIN_INLIER_RATIO,
                    )
                ),
            )
        except Exception as exc:  # noqa: BLE001 - verification is a supported API
            raise FeatureMatchError(
                NEURAL_VERIFICATION_FAILED,
                "The neural matches could not be geometrically verified.",
            ) from exc


__all__ = [
    "AlikedLightGlueBackend",
    "MIN_FREE_VRAM_MB",
    "MIN_KEYPOINTS_PER_IMAGE",
    "NeuralVersions",
    "model_cache_path",
    "resize_scale",
    "restore_keypoints",
    "runtime_versions",
    "validate_features",
    "verify_model_files",
]
