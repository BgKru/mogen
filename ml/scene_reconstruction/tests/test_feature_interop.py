"""Actual-binary interoperability test for ALIKED + LightGlue (12 Section 10.2).

Opt-in because it loads the neural models and needs a multi-view dataset and,
for GPU mode, a CUDA device:

    RUN_FEATURE_INTEROP_TEST=1 SCENE_TEST_IMAGES=/data/Sceaux \
        python -m pytest -m scene_binaries -k neural

It prepares a real dataset, extracts ALIKED features, matches with LightGlue,
imports into a fresh COLMAP database through pycolmap 4.2.1, verifies the
matches, runs the pinned ``colmap mapper`` and inspects the model with the
existing selector. A mocked database is not used anywhere in this test.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from scene_reconstruction.colmap_runner import ColmapRunner, read_database_stats
from scene_reconstruction.config import SceneConfig
from scene_reconstruction.dataset import SourceImage, prepare_dataset, workspace_paths
from scene_reconstruction.feature_matching import (
    build_feature_backend,
    build_feature_manifest,
    feature_manifest_path,
    manifest_matches,
    write_feature_manifest,
)
from scene_reconstruction.feature_profiles import BACKEND_ALIKED_LIGHTGLUE
from scene_reconstruction.reconstruction_selector import (
    inspect_model,
    select_reconstruction,
)


@pytest.mark.scene_binaries
@pytest.mark.slow
def test_neural_database_is_accepted_by_the_pinned_colmap_binary(tmp_path):
    if os.environ.get("RUN_FEATURE_INTEROP_TEST") != "1":
        pytest.skip("set RUN_FEATURE_INTEROP_TEST=1 with SCENE_TEST_IMAGES to run")
    directory = Path(os.environ.get("SCENE_TEST_IMAGES", ""))
    if not directory.is_dir():
        pytest.skip("SCENE_TEST_IMAGES does not point at a directory")
    images = sorted(
        path
        for path in directory.rglob("*")
        if path.is_file() and path.suffix.lower() in {".jpg", ".jpeg", ".png"}
    )
    if len(images) < 3:
        pytest.skip("the configured dataset needs at least three photographs")
    images = images[:6]

    config = SceneConfig(
        feature_backend=BACKEND_ALIKED_LIGHTGLUE,
        feature_profile="aliked_lightglue",
        feature_device=os.environ.get("FEATURE_TEST_DEVICE", "auto"),
        feature_image_max_size=960,
        feature_max_keypoints=1024,
        min_registered_images=3,
        min_registration_ratio=0.3,
        min_sparse_points=1,
    )
    dataset = prepare_dataset(
        [SourceImage.from_path(path) for path in images], work_dir=tmp_path / "task"
    )
    paths = workspace_paths(dataset.work_dir)
    database = paths["colmap"] / "database.db"

    backend = build_feature_backend(config)
    runtime = backend.verify_runtime(config)
    assert runtime.available is True
    assert runtime.versions["pycolmap"] == "4.2.1"

    extraction = backend.extract_features(
        dataset,
        images_dir=paths["images"],
        database_path=database,
        work_dir=paths["root"],
        on_poll=lambda: None,
    )
    assert extraction.images == dataset.image_count
    assert extraction.keypoints_total >= dataset.image_count * 16

    matching = backend.match_features(
        dataset,
        images_dir=paths["images"],
        database_path=database,
        work_dir=paths["root"],
        on_poll=lambda: None,
    )
    stats = read_database_stats(database)
    assert stats.images == dataset.image_count
    assert stats.keypoints > 0
    assert stats.matched_pairs > 0
    assert stats.verified_pairs > 0
    assert stats.largest_component >= 2
    assert matching.verified_pairs == stats.verified_pairs

    manifest = build_feature_manifest(
        dataset,
        config,
        backend=backend.name,
        colmap_version="COLMAP 4.2.1",
    )
    write_feature_manifest(feature_manifest_path(paths["colmap"]), manifest)
    assert manifest_matches(feature_manifest_path(paths["colmap"]), manifest)

    runner = ColmapRunner(config)
    sparse = runner.reconstruct_sparse(
        images_dir=paths["images"],
        database_path=database,
        sparse_dir=paths["colmap_sparse"],
        log_path=paths["logs"] / "mapper.log",
    )
    models = list(sparse.model_dirs)
    assert models, "the pinned COLMAP mapper produced no model"

    candidates = []
    for model_dir in models:
        text_dir = paths["colmap"] / "models_txt" / model_dir.name
        runner.convert_model(
            model_dir=model_dir,
            output_dir=text_dir,
            log_path=paths["logs"] / "convert.log",
        )
        candidates.append(inspect_model(model_dir, text_dir, dataset.image_count))
    selection = select_reconstruction(candidates, config)
    assert selection.selected.registered_images >= 3
    assert selection.selected.points > 0
