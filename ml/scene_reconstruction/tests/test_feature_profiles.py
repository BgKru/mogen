"""Feature backend/profile configuration (increment 12, Section 6)."""

from __future__ import annotations

import pytest

from scene_reconstruction.config import SceneConfig
from scene_reconstruction.feature_profiles import (
    ALIKED_WEIGHTS_SHA256,
    BACKEND_ALIKED_LIGHTGLUE,
    BACKEND_COLMAP_SIFT,
    FEATURE_BACKENDS,
    FeatureProfileError,
    model_manifest,
    normalize_backend,
    resolve_profile,
)


def test_defaults_keep_sift_as_the_production_baseline():
    config = SceneConfig()
    assert config.feature_backend == BACKEND_COLMAP_SIFT
    assert config.feature_profile == "sift_default"
    assert config.feature_fallback_to_sift is True
    assert config.effective_max_keypoints() == 0
    assert config.resolved_feature_profile.is_neural is False


def test_neural_profile_resolves_and_is_opt_in():
    config = SceneConfig(
        feature_backend=BACKEND_ALIKED_LIGHTGLUE,
        feature_profile="aliked_lightglue",
    )
    assert config.resolved_feature_profile.is_neural is True
    assert config.effective_max_keypoints() == 2048
    assert config.feature_parameters()["match_threshold"] == 0.1


def test_fast_profile_keeps_its_reduced_budget_even_with_a_larger_ceiling():
    config = SceneConfig(
        feature_backend=BACKEND_ALIKED_LIGHTGLUE,
        feature_profile="aliked_lightglue_fast",
        feature_max_keypoints=4096,
    )
    assert config.effective_max_keypoints() == 1024


def test_backend_profile_mismatch_is_rejected():
    with pytest.raises(ValueError, match="profile"):
        SceneConfig(
            feature_backend=BACKEND_COLMAP_SIFT,
            feature_profile="aliked_lightglue",
        )
    with pytest.raises(ValueError, match="ALIKED_LIGHTGLUE"):
        SceneConfig(
            feature_backend=BACKEND_ALIKED_LIGHTGLUE,
            feature_profile="sift_default",
        )
    with pytest.raises(FeatureProfileError):
        resolve_profile("NOT_A_BACKEND", "sift_default")
    with pytest.raises(FeatureProfileError):
        normalize_backend("sift")


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("feature_max_keypoints", 16),
        ("feature_image_max_size", 128),
        ("feature_sequential_overlap", 0),
        ("feature_min_matches", -1),
        ("feature_match_threshold", 1.5),
        ("feature_device", "tpu"),
        ("feature_max_vram_mb", 128),
        ("feature_max_pairs", 0),
        ("feature_pair_strategy", "RANDOM"),
    ],
)
def test_invalid_feature_settings_are_rejected(field, value):
    with pytest.raises(ValueError):
        SceneConfig(**{field: value})


def test_manifest_records_every_output_affecting_feature_setting():
    config = SceneConfig(
        feature_backend=BACKEND_ALIKED_LIGHTGLUE,
        feature_profile="aliked_lightglue",
    )
    manifest = config.as_manifest()
    features = manifest["features"]
    assert features["backend"] == BACKEND_ALIKED_LIGHTGLUE
    assert features["profile"] == "aliked_lightglue"
    assert features["pair_strategy"] == "EXHAUSTIVE"
    assert features["image_max_size"] == 1600
    assert features["max_keypoints"] == 2048
    assert set(features) >= {
        "backend",
        "profile",
        "fallback_to_sift",
        "max_keypoints",
        "image_max_size",
        "pair_strategy",
        "sequential_overlap",
        "min_matches",
        "match_threshold",
        "device",
        "max_vram_mb",
        "max_pairs",
    }


def test_model_manifest_pins_the_tested_checkpoints():
    manifest = model_manifest()
    assert manifest["extractor"] == "aliked-n16"
    assert manifest["extractor_sha256"] == ALIKED_WEIGHTS_SHA256
    assert manifest["descriptor_dim"] == 128
    assert len(manifest["matcher_revision"]) == 40


def test_backend_choices_are_stable():
    assert FEATURE_BACKENDS == (BACKEND_COLMAP_SIFT, BACKEND_ALIKED_LIGHTGLUE)
