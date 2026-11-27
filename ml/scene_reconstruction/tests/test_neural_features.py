"""Neural adapter helpers that can be tested without a GPU (increment 12)."""

from __future__ import annotations

import json

import numpy as np
import pytest

from scene_reconstruction import neural_features
from scene_reconstruction.config import SceneConfig
from scene_reconstruction.diagnostics import ReconstructionDiagnostics
from scene_reconstruction.exceptions import (
    INSUFFICIENT_FEATURES,
    NEURAL_CUDA_UNAVAILABLE,
    NEURAL_MODEL_UNAVAILABLE,
    NEURAL_RESOURCE_EXHAUSTED,
    NEURAL_RUNTIME_UNAVAILABLE,
    FeatureMatchError,
    ResourceError,
    ToolError,
)
from scene_reconstruction.feature_profiles import (
    ALIKED_WEIGHTS_FILENAME,
    LIGHTGLUE_WEIGHTS_FILENAME,
)


def test_resize_scale_never_upscales():
    assert neural_features.resize_scale(3200, 2400, 1600) == pytest.approx(0.5)
    assert neural_features.resize_scale(800, 600, 1600) == 1.0
    with pytest.raises(FeatureMatchError):
        neural_features.resize_scale(0, 600, 1600)


def test_keypoints_are_restored_to_original_coordinates_and_clipped():
    keypoints = np.array(
        [[0.0, 0.0], [10.0, 20.0], [600.0, 500.0], [100.0, np.nan]], dtype=np.float32
    )
    restored = neural_features.restore_keypoints(keypoints, scale=0.5, width=1000, height=800)
    # (kp + 0.5) / 0.5 - 0.5 == 2*kp + 0.5
    assert restored[0].tolist() == pytest.approx([0.5, 0.5])
    assert restored[1].tolist() == pytest.approx([20.5, 40.5])
    assert restored.shape[0] == 2  # out-of-bounds and non-finite detections dropped


def test_malformed_or_insufficient_features_are_rejected():
    with pytest.raises(FeatureMatchError):
        neural_features.validate_features(np.zeros((20, 3)), np.zeros((20, 128)), expected_dim=128)
    with pytest.raises(FeatureMatchError):
        neural_features.validate_features(np.zeros((20, 2)), np.zeros((19, 128)), expected_dim=128)
    with pytest.raises(FeatureMatchError):
        neural_features.validate_features(np.zeros((20, 2)), np.zeros((20, 64)), expected_dim=128)
    with pytest.raises(FeatureMatchError) as error:
        neural_features.validate_features(np.zeros((4, 2)), np.zeros((4, 128)), expected_dim=128)
    assert error.value.error_code == INSUFFICIENT_FEATURES
    broken = np.zeros((20, 2))
    broken[0, 0] = np.nan
    with pytest.raises(FeatureMatchError):
        neural_features.validate_features(broken, np.zeros((20, 128)), expected_dim=128)


def test_model_cache_uses_torch_home(monkeypatch, tmp_path):
    monkeypatch.setenv("TORCH_HOME", str(tmp_path))
    assert neural_features.model_cache_path(ALIKED_WEIGHTS_FILENAME) == (
        tmp_path / "hub" / "checkpoints" / ALIKED_WEIGHTS_FILENAME
    )


def test_missing_or_tampered_checkpoints_fail_with_a_model_error(monkeypatch, tmp_path):
    monkeypatch.setenv("TORCH_HOME", str(tmp_path))
    directory = tmp_path / "hub" / "checkpoints"
    directory.mkdir(parents=True)
    with pytest.raises(ToolError) as missing:
        neural_features.verify_model_files()
    assert missing.value.error_code == NEURAL_MODEL_UNAVAILABLE

    (directory / ALIKED_WEIGHTS_FILENAME).write_bytes(b"not the model")
    (directory / LIGHTGLUE_WEIGHTS_FILENAME).write_bytes(b"not the matcher")
    with pytest.raises(ToolError) as tampered:
        neural_features.verify_model_files()
    assert tampered.value.error_code == NEURAL_MODEL_UNAVAILABLE


def test_explicit_cuda_fails_clearly_when_unavailable():
    class FakeCuda:
        @staticmethod
        def is_available() -> bool:
            return False

    class FakeTorch:
        cuda = FakeCuda()

    config = SceneConfig(feature_device="cuda")
    with pytest.raises(ResourceError) as error:
        neural_features._device_for(config, FakeTorch())
    assert error.value.error_code == NEURAL_CUDA_UNAVAILABLE


def test_device_auto_falls_back_to_cpu_or_cuda():
    class FakeCuda:
        def __init__(self, available: bool) -> None:
            self.available = available

        def is_available(self) -> bool:
            return self.available

    class FakeTorch:
        def __init__(self, available: bool) -> None:
            self.cuda = FakeCuda(available)

    assert neural_features._device_for(SceneConfig(), FakeTorch(False)) == "cpu"
    assert neural_features._device_for(SceneConfig(), FakeTorch(True)) == "cuda"
    assert (
        neural_features._device_for(SceneConfig(feature_device="cuda"), FakeTorch(True)) == "cuda"
    )


def test_runtime_import_failure_is_a_stable_runtime_error(monkeypatch):
    def unavailable():
        raise ToolError(NEURAL_RUNTIME_UNAVAILABLE, "not installed")

    monkeypatch.setattr(neural_features, "_import_runtime", unavailable)
    with pytest.raises(ToolError) as error:
        neural_features.runtime_versions()
    assert error.value.error_code == NEURAL_RUNTIME_UNAVAILABLE


def test_oom_mapping_is_a_resource_error():
    error = neural_features._as_resource_error(MemoryError("out of memory"))
    assert isinstance(error, ResourceError)
    assert error.error_code == NEURAL_RESOURCE_EXHAUSTED


def test_diagnostics_expose_only_compact_feature_metrics():
    diagnostics = ReconstructionDiagnostics(
        feature_backend="ALIKED_LIGHTGLUE",
        feature_profile="aliked_lightglue",
        feature_actual_backend="COLMAP_SIFT",
        feature_fallback_used=True,
        feature_fallback_reason="NEURAL_RESOURCE_EXHAUSTED",
        feature_versions={"torch": "2.14.1", "pycolmap": "4.2.1"},
        feature_extraction={"images": 11, "keypoints_total": 22528},
        feature_matching={"pairs": 55, "verified_pairs": 54},
    )
    document = diagnostics.as_metadata()["features"]
    assert document["requested_backend"] == "ALIKED_LIGHTGLUE"
    assert document["backend"] == "COLMAP_SIFT"
    assert document["fallback"] == {
        "used": True,
        "reason": "NEURAL_RESOURCE_EXHAUSTED",
    }
    serialized = json.dumps(document)
    assert "descriptor" not in serialized.lower()
    assert "tensor" not in serialized.lower()
    assert "2.14.1" in serialized and "4.2.1" in serialized
    assert "/tmp" not in serialized
