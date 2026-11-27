"""Generator contract, factory and configuration tests (increment 13, CPU only).

These tests never load a real model: they prove the allowlist, the configuration
validation and the protocol shape without requiring weights or a GPU.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

import object_generation.generator_factory as factory_module
from object_generation.config import (
    ObjectGenerationConfig,
    SF3DConfig,
)
from object_generation.exceptions import GENERATOR_NOT_AVAILABLE, GeneratorUnavailableError
from object_generation.generator import TRIPOSR_SOURCE_REVISION, TripoSRAdapter, cuda_peak_bytes
from object_generation.generator_base import ObjectGenerator
from object_generation.generator_factory import available_generators, create_generator


def _config(tmp_path: Path, **overrides) -> ObjectGenerationConfig:
    values = {
        "model_dir": tmp_path / "model",
        "model_revision": "test-revision",
        "model_sha256": "",
        "device": "cpu",
    }
    values.update(overrides)
    return ObjectGenerationConfig(**values)


def _sf3d(tmp_path: Path, **overrides) -> SF3DConfig:
    values = {
        "enabled": True,
        "model_revision": "f0c9a8ffd62cb1bbc8a7a53c9f87a0be1b6be778",
        "model_dir": tmp_path / "sf3d",
        "manifest_path": tmp_path / "sf3d" / "model-manifest.json",
    }
    values.update(overrides)
    return SF3DConfig(**values)


def test_triposr_is_the_default_generator(tmp_path: Path) -> None:
    config = _config(tmp_path)

    assert config.generator == "triposr"
    assert config.generator_fallback is False
    assert "sf3d" in available_generators()
    adapter = create_generator(config, load=False)
    assert isinstance(adapter, ObjectGenerator)
    assert adapter.name == "triposr"
    assert adapter.revision == TRIPOSR_SOURCE_REVISION
    assert adapter.model_id == "stabilityai/TripoSR"
    assert adapter.capabilities().mode == "rgb_composite"


def test_triposr_capabilities_follow_the_configuration(tmp_path: Path) -> None:
    adapter = create_generator(_config(tmp_path, remove_background=False), load=False)

    capabilities = adapter.capabilities()

    assert capabilities.background_removal is False
    assert capabilities.input_size == 512
    assert capabilities.color_mode == "RGB"
    assert capabilities.as_metadata()["mode"] == "rgb_composite"


def test_sf3d_is_rejected_unless_explicitly_enabled(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="OBJECT_SF3D_ENABLED"):
        _config(tmp_path, generator="sf3d")


def test_unknown_and_blocked_generators_are_rejected(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="Unsupported object generator"):
        _config(tmp_path, generator="magic")

    with pytest.raises(ValueError, match="Hunyuan3D"):
        _config(tmp_path, generator="hunyuan3d")

    # The factory also refuses the blocked name when it is reached directly.
    with pytest.raises(GeneratorUnavailableError) as excinfo:
        factory_module._build(SimpleNamespace(generator="hunyuan3d"))
    assert excinfo.value.error_code == GENERATOR_NOT_AVAILABLE


def test_sf3d_configuration_is_validated(tmp_path: Path) -> None:
    config = _config(tmp_path, generator="sf3d", sf3d=_sf3d(tmp_path))

    adapter = create_generator(config, load=False)

    assert adapter.name == "sf3d"
    assert adapter.revision.startswith("ff21fc49")
    assert adapter.model_revision == "f0c9a8ffd62cb1bbc8a7a53c9f87a0be1b6be778"
    assert adapter.capabilities().mode == "rgba_foreground"
    assert adapter.capabilities().alpha is True
    assert adapter.capabilities().input_size is None


@pytest.mark.parametrize(
    "overrides",
    [
        {"texture_resolution": 64},
        {"texture_resolution": 8192},
        {"remesh": "smooth"},
        {"target_vertex_count": 10},
        {"model_dir": Path("models/sf3d")},
        {"manifest_path": Path("manifest.json")},
        {"enabled": True, "model_revision": ""},
        {"enabled": True, "model_revision": "main"},
    ],
)
def test_sf3d_rejects_invalid_settings(tmp_path: Path, overrides: dict) -> None:
    with pytest.raises(ValueError):
        _sf3d(tmp_path, **overrides)


def test_sf3d_remesh_and_texture_resolution_are_recorded(tmp_path: Path) -> None:
    settings = _sf3d(tmp_path, texture_resolution=2048, remesh="triangle", target_vertex_count=5000)

    metadata = settings.as_metadata()

    assert metadata["texture_resolution"] == 2048
    assert metadata["remesh"] == "triangle"
    assert metadata["target_vertex_count"] == 5000


def test_cuda_peak_is_omitted_off_device() -> None:
    assert cuda_peak_bytes("cpu") == (None, None)


def test_the_factory_reuses_one_adapter_per_configuration(tmp_path: Path) -> None:
    config = _config(tmp_path)

    first = create_generator(config, load=False)
    second = create_generator(config, load=False)

    assert first is second
    assert isinstance(first, TripoSRAdapter)
