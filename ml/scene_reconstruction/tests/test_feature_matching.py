"""Feature backend contract, pairs, manifest and fallback (increment 12)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scene_reconstruction import pipeline as pipeline_module
from scene_reconstruction.colmap_runner import (
    feature_extraction_command,
    feature_matching_command,
)
from scene_reconstruction.config import SceneConfig
from scene_reconstruction.dataset import SourceImage, prepare_dataset, workspace_paths
from scene_reconstruction.exceptions import (
    FEATURE_PAIR_LIMIT_EXCEEDED,
    NEURAL_FEATURE_EXTRACTION_FAILED,
    NEURAL_MATCHING_FAILED,
    FeatureMatchError,
)
from scene_reconstruction.feature_matching import (
    FeatureExtractionResult,
    RuntimeInfo,
    SiftBackend,
    build_feature_backend,
    build_feature_manifest,
    feature_manifest_path,
    features_path,
    generate_pairs,
    manifest_matches,
    read_feature_manifest,
    write_feature_manifest,
)
from scene_reconstruction.feature_profiles import (
    BACKEND_ALIKED_LIGHTGLUE,
    BACKEND_COLMAP_SIFT,
)
from scene_reconstruction.pipeline import PhotogrammetryReconstructor

from .helpers import gradient_image_bytes
from .test_pipeline import FakeColmap


def _dataset(tmp_path: Path):
    sources = [
        SourceImage.from_bytes(gradient_image_bytes(seed=index), filename=f"photo-{index}.jpg")
        for index in range(3)
    ]
    return prepare_dataset(sources, work_dir=tmp_path / "task")


def _config(**overrides):
    values = {
        "colmap_use_gpu": False,
        "min_registered_images": 2,
        "min_registration_ratio": 0.3,
        "min_sparse_points": 1,
    }
    values.update(overrides)
    return SceneConfig(**values)


class FailingNeural:
    """A neural backend that fails at the configured stage."""

    name = BACKEND_ALIKED_LIGHTGLUE

    def __init__(self, *, fail_at: str) -> None:
        self.fail_at = fail_at
        self.calls: list[str] = []

    def verify_runtime(self, config):
        self.calls.append("VERIFY")
        return RuntimeInfo(
            backend=self.name,
            available=True,
            device="cpu",
            versions={"extractor": "fake"},
        )

    def extract_features(self, dataset, *, images_dir, database_path, work_dir, on_poll):
        self.calls.append("EXTRACT")
        if self.fail_at == "extract":
            raise FeatureMatchError(NEURAL_FEATURE_EXTRACTION_FAILED, "injected extraction failure")
        from .helpers import create_colmap_database

        create_colmap_database(database_path, images=dataset.image_count, verified_pairs=[])
        return FeatureExtractionResult(
            backend=self.name,
            profile="aliked_lightglue",
            images=dataset.image_count,
            keypoints_total=100,
            keypoints_min=100,
            keypoints_max=100,
            seconds=0.01,
            device="cpu",
        )

    def match_features(self, dataset, *, images_dir, database_path, work_dir, on_poll):
        self.calls.append("MATCH")
        raise FeatureMatchError(NEURAL_MATCHING_FAILED, "injected matching failure")


def _install_backend(monkeypatch, neural):
    def factory(config, *, colmap_runner=None):
        if config.feature_backend == BACKEND_COLMAP_SIFT:
            return SiftBackend(config, colmap=colmap_runner)
        return neural

    monkeypatch.setattr(pipeline_module, "build_feature_backend", factory)


def test_default_sift_commands_are_unchanged():
    config = SceneConfig()
    extraction = feature_extraction_command(
        config, images_dir=Path("/tmp/images"), database_path=Path("/tmp/database.db")
    )
    matching = feature_matching_command(config, database_path=Path("/tmp/database.db"))
    assert extraction[1] == "feature_extractor"
    assert matching[1] == "exhaustive_matcher"
    assert extraction[-2:] == ["--FeatureExtraction.num_threads", "4"]
    assert matching[-2:] == ["--FeatureMatching.num_threads", "4"]


def test_factory_dispatches_the_configured_backend():
    sift = build_feature_backend(SceneConfig())
    assert isinstance(sift, SiftBackend)
    assert sift.name == BACKEND_COLMAP_SIFT
    neural = build_feature_backend(
        SceneConfig(
            feature_backend=BACKEND_ALIKED_LIGHTGLUE,
            feature_profile="aliked_lightglue",
        )
    )
    assert neural.name == BACKEND_ALIKED_LIGHTGLUE


def test_sift_backend_delegates_to_the_existing_runner(tmp_path):
    dataset = _dataset(tmp_path)
    calls: list[str] = []
    colmap = FakeColmap(calls)
    backend = SiftBackend(_config(), colmap=colmap)
    database = tmp_path / "colmap" / "database.db"
    database.parent.mkdir(parents=True)
    extraction = backend.extract_features(
        dataset,
        images_dir=dataset.images_dir,
        database_path=database,
        work_dir=tmp_path,
        on_poll=lambda: None,
    )
    matching = backend.match_features(
        dataset,
        images_dir=dataset.images_dir,
        database_path=database,
        work_dir=tmp_path,
        on_poll=lambda: None,
    )
    assert extraction.images == dataset.image_count
    assert matching.verified_pairs > 0
    assert calls[:2] == ["FEATURE_EXTRACTION", "FEATURE_MATCHING"]


def test_pairs_are_deterministic_and_bounded():
    names = ["image_003.jpg", "image_001.jpg", "image_002.jpg"]
    exhaustive = generate_pairs(names, strategy="EXHAUSTIVE", sequential_overlap=1, max_pairs=10)
    assert exhaustive == [
        ("image_001.jpg", "image_002.jpg"),
        ("image_001.jpg", "image_003.jpg"),
        ("image_002.jpg", "image_003.jpg"),
    ]
    sequential = generate_pairs(names, strategy="SEQUENTIAL", sequential_overlap=1, max_pairs=10)
    assert sequential == [
        ("image_003.jpg", "image_001.jpg"),
        ("image_001.jpg", "image_002.jpg"),
    ]
    wide = generate_pairs(names, strategy="SEQUENTIAL", sequential_overlap=2, max_pairs=10)
    assert wide[0] == ("image_003.jpg", "image_001.jpg")
    assert ("image_003.jpg", "image_002.jpg") in wide
    with pytest.raises(FeatureMatchError) as error:
        generate_pairs(names, strategy="EXHAUSTIVE", sequential_overlap=1, max_pairs=1)
    assert error.value.error_code == FEATURE_PAIR_LIMIT_EXCEEDED


def test_manifest_fingerprints_images_backend_and_parameters(tmp_path):
    dataset = _dataset(tmp_path)
    config = SceneConfig(
        feature_backend=BACKEND_ALIKED_LIGHTGLUE,
        feature_profile="aliked_lightglue",
        feature_pair_strategy="SEQUENTIAL",
    )
    manifest = build_feature_manifest(
        dataset, config, backend=BACKEND_ALIKED_LIGHTGLUE, colmap_version="COLMAP 4.2.1"
    )
    assert manifest["backend"] == BACKEND_ALIKED_LIGHTGLUE
    assert manifest["parameters"]["pair_strategy"] == "SEQUENTIAL"
    assert manifest["colmap_version"] == "COLMAP 4.2.1"
    assert len(manifest["dataset"]["images"]) == 3
    assert all(len(image["sha256"]) == 64 for image in manifest["dataset"]["images"])

    path = feature_manifest_path(tmp_path / "colmap")
    write_feature_manifest(path, manifest)
    assert manifest_matches(path, manifest) is True
    assert read_feature_manifest(path) == json.loads(path.read_text(encoding="utf-8"))

    changed_profile = dict(manifest)
    changed_profile["profile"] = "aliked_lightglue_fast"
    assert manifest_matches(path, changed_profile) is False
    changed_backend = dict(manifest)
    changed_backend["backend"] = BACKEND_COLMAP_SIFT
    assert manifest_matches(path, changed_backend) is False
    changed_parameter = json.loads(json.dumps(manifest))
    changed_parameter["parameters"]["max_keypoints"] = 1024
    assert manifest_matches(path, changed_parameter) is False


def test_manifest_mismatch_forces_a_clean_rebuild(tmp_path, monkeypatch):
    dataset = _dataset(tmp_path)
    calls: list[str] = []
    colmap = FakeColmap(calls)
    config = _config()
    recon = PhotogrammetryReconstructor(config, colmap=colmap)
    recon._diagnostics.tool_versions = {"colmap": "COLMAP 4.2.1"}
    paths = workspace_paths(dataset.work_dir)
    recon._sparse_stages(dataset, paths)
    first = list(calls)
    assert first.count("FEATURE_EXTRACTION") == 1

    manifest_path = feature_manifest_path(paths["colmap"])
    stored = read_feature_manifest(manifest_path)
    assert stored is not None
    stored["parameters"]["max_keypoints"] = 123
    write_feature_manifest(manifest_path, stored)

    recon2 = PhotogrammetryReconstructor(config, colmap=colmap)
    recon2._diagnostics.tool_versions = {"colmap": "COLMAP 4.2.1"}
    recon2._sparse_stages(dataset, paths)
    # The mismatched manifest invalidates both feature stages and dependants.
    assert calls.count("FEATURE_EXTRACTION") == 2
    assert calls.count("FEATURE_MATCHING") == 2
    assert calls.count("SPARSE_RECONSTRUCTION") == 2


@pytest.mark.parametrize("fail_at", ["extract", "match"])
def test_recoverable_neural_failure_rebuilds_clean_sift(tmp_path, monkeypatch, fail_at):
    dataset = _dataset(tmp_path)
    calls: list[str] = []
    colmap = FakeColmap(calls)
    neural = FailingNeural(fail_at=fail_at)
    _install_backend(monkeypatch, neural)
    config = _config(
        feature_backend=BACKEND_ALIKED_LIGHTGLUE,
        feature_profile="aliked_lightglue",
    )
    recon = PhotogrammetryReconstructor(config, colmap=colmap)
    recon._diagnostics.tool_versions = {"colmap": "COLMAP 4.2.1"}
    paths = workspace_paths(dataset.work_dir)
    recon._sparse_stages(dataset, paths)

    assert neural.calls[0] == "VERIFY"
    assert recon._diagnostics.feature_fallback_used is True
    assert recon._diagnostics.feature_fallback_reason in {
        NEURAL_FEATURE_EXTRACTION_FAILED,
        NEURAL_MATCHING_FAILED,
    }
    assert recon._diagnostics.feature_actual_backend == BACKEND_COLMAP_SIFT
    manifest = read_feature_manifest(feature_manifest_path(paths["colmap"]))
    assert manifest is not None and manifest["backend"] == BACKEND_COLMAP_SIFT
    assert features_path(paths["colmap"]).exists() is False
    assert calls.count("FEATURE_EXTRACTION") >= 1
    assert calls.count("FEATURE_MATCHING") >= 1
    assert calls.count("SPARSE_RECONSTRUCTION") == 1


def test_fallback_disabled_raises_the_neural_error(tmp_path, monkeypatch):
    dataset = _dataset(tmp_path)
    calls: list[str] = []
    colmap = FakeColmap(calls)
    _install_backend(monkeypatch, FailingNeural(fail_at="extract"))
    config = _config(
        feature_backend=BACKEND_ALIKED_LIGHTGLUE,
        feature_profile="aliked_lightglue",
        feature_fallback_to_sift=False,
    )
    recon = PhotogrammetryReconstructor(config, colmap=colmap)
    recon._diagnostics.tool_versions = {"colmap": "COLMAP 4.2.1"}
    paths = workspace_paths(dataset.work_dir)
    with pytest.raises(FeatureMatchError) as error:
        recon._sparse_stages(dataset, paths)
    assert error.value.error_code == NEURAL_FEATURE_EXTRACTION_FAILED
    assert recon._diagnostics.feature_fallback_used is False
    assert calls == []
