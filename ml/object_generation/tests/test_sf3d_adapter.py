"""SF3D adapter tests (increment 13, CPU only, fake upstream model).

The real upstream ``sf3d`` package is not importable in the plain unit-test
environment; these tests inject a deterministic fake so the adapter's manifest
verification, error mapping, metadata and preprocessing contract are covered
without weights.
"""

from __future__ import annotations

import hashlib
import json
import sys
import types
from pathlib import Path

import pytest
from PIL import Image

from object_generation.config import ObjectGenerationConfig, SF3DConfig
from object_generation.exceptions import (
    GPU_OUT_OF_MEMORY,
    MODEL_INFERENCE_FAILED,
    MODEL_WEIGHTS_CHECKSUM_MISMATCH,
    MODEL_WEIGHTS_MISSING,
    InferenceError,
    ModelUnavailableError,
)
from object_generation.sf3d.adapter import SF3D_SOURCE_REVISION, SF3DAdapter
from object_generation.sf3d.loader import verify_weights
from tests.helpers import textured_box

REVISION = "f0c9a8ffd62cb1bbc8a7a53c9f87a0be1b6be778"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _weights(tmp_path: Path, *, size: int = 1024 * 1024 + 8) -> tuple[Path, Path]:
    model_dir = tmp_path / "sf3d"
    model_dir.mkdir(parents=True)
    (model_dir / "config.yaml").write_text("latents: 8\n", encoding="utf-8")
    (model_dir / "model.safetensors").write_bytes(b"\x01" * size)
    manifest = {
        "model_id": "stabilityai/stable-fast-3d",
        "model_revision": REVISION,
        "files": {
            "config.yaml": {"sha256": _sha256(model_dir / "config.yaml")},
            "model.safetensors": {"sha256": _sha256(model_dir / "model.safetensors")},
        },
    }
    manifest_path = model_dir / "model-manifest.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    return model_dir, manifest_path


class FakeModel:
    def __init__(self, *, error: Exception | None = None, mesh=None) -> None:
        self._error = error
        self._mesh = mesh or textured_box()
        self.to_calls: list[str] = []
        self.eval_called = False
        self.run_calls: list[dict] = []

    def to(self, device: str) -> FakeModel:
        self.to_calls.append(device)
        return self

    def eval(self) -> FakeModel:
        self.eval_called = True
        return self

    def parameters(self):
        return iter(())

    def run_image(self, image, *, bake_resolution, remesh, vertex_count):
        self.run_calls.append(
            {
                "mode": image.mode,
                "size": image.size,
                "bake_resolution": bake_resolution,
                "remesh": remesh,
                "vertex_count": vertex_count,
            }
        )
        if self._error is not None:
            raise self._error
        return self._mesh, {}


class FakeSF3D:
    created: list[FakeModel] = []

    @classmethod
    def from_pretrained(cls, path, config_name, weight_name):
        model = FakeModel()
        cls.created.append(model)
        return model


@pytest.fixture
def fake_upstream(monkeypatch):
    package = types.ModuleType("sf3d")
    package.__path__ = []  # mark it as a package
    system = types.ModuleType("sf3d.system")
    system.SF3D = FakeSF3D
    monkeypatch.setitem(sys.modules, "sf3d", package)
    monkeypatch.setitem(sys.modules, "sf3d.system", system)
    FakeSF3D.created = []
    return FakeSF3D


def _adapter(tmp_path: Path, model_dir: Path, manifest_path: Path) -> SF3DAdapter:
    config = ObjectGenerationConfig(
        model_dir=tmp_path / "triposr",
        model_revision="test",
        model_sha256="",
        device="cpu",
        generator="sf3d",
        sf3d=SF3DConfig(
            enabled=True,
            model_revision=REVISION,
            model_dir=model_dir,
            manifest_path=manifest_path,
            texture_resolution=128,
        ),
    )
    return SF3DAdapter(config)


def test_verify_weights_accepts_a_matching_manifest(tmp_path: Path) -> None:
    model_dir, manifest_path = _weights(tmp_path)

    weights = verify_weights(
        SF3DConfig(
            enabled=True,
            model_revision=REVISION,
            model_dir=model_dir,
            manifest_path=manifest_path,
        )
    )

    assert weights.model_revision == REVISION
    assert weights.weight_sha256 == _sha256(model_dir / "model.safetensors")


def test_verify_weights_rejects_a_changed_checkpoint(tmp_path: Path) -> None:
    model_dir, manifest_path = _weights(tmp_path)
    (model_dir / "model.safetensors").write_bytes(b"\x02" * (1024 * 1024 + 8))

    with pytest.raises(ModelUnavailableError) as excinfo:
        verify_weights(
            SF3DConfig(
                enabled=True,
                model_revision=REVISION,
                model_dir=model_dir,
                manifest_path=manifest_path,
            )
        )

    assert excinfo.value.error_code == MODEL_WEIGHTS_CHECKSUM_MISMATCH


def test_verify_weights_rejects_a_missing_manifest(tmp_path: Path) -> None:
    model_dir, manifest_path = _weights(tmp_path)
    manifest_path.unlink()

    with pytest.raises(ModelUnavailableError) as excinfo:
        verify_weights(
            SF3DConfig(
                enabled=True,
                model_revision=REVISION,
                model_dir=model_dir,
                manifest_path=manifest_path,
            )
        )

    assert excinfo.value.error_code == MODEL_WEIGHTS_MISSING


def test_verify_weights_rejects_a_different_revision(tmp_path: Path) -> None:
    model_dir, manifest_path = _weights(tmp_path)

    with pytest.raises(ModelUnavailableError) as excinfo:
        verify_weights(
            SF3DConfig(
                enabled=True,
                model_revision="0000000000000000000000000000000000000000",
                model_dir=model_dir,
                manifest_path=manifest_path,
            )
        )

    assert excinfo.value.error_code == MODEL_WEIGHTS_CHECKSUM_MISMATCH


def test_adapter_loads_and_generates_a_textured_result(tmp_path: Path, fake_upstream) -> None:
    model_dir, manifest_path = _weights(tmp_path)
    adapter = _adapter(tmp_path, model_dir, manifest_path)
    image = Image.new("RGBA", (96, 96), (10, 20, 30, 255))

    adapter.load()
    result = adapter.generate(image, started_at=0.0)

    assert result.name == "sf3d"
    assert result.revision == SF3D_SOURCE_REVISION
    assert result.model_revision == REVISION
    assert result.has_textures is True
    assert result.texture_resolution == 64
    assert result.inference_seconds >= 0.0
    metadata = result.metadata()
    assert metadata["name"] == "sf3d"
    assert "peak_cuda_allocated_bytes" not in metadata  # CPU: omitted, never zero
    assert "diagnostics" in metadata
    assert metadata["diagnostics"]["preprocessing_profile"] == "sf3d_default"
    # The adapter passes the prepared RGBA image through unchanged and uses the
    # configured texture resolution/remesh settings.
    call = fake_upstream.created[0].run_calls[0]
    assert call["mode"] == "RGBA"
    assert call["bake_resolution"] == 128
    assert call["remesh"] == "none"


def test_adapter_maps_out_of_memory_to_a_stable_code(tmp_path: Path, fake_upstream) -> None:
    model_dir, manifest_path = _weights(tmp_path)
    adapter = _adapter(tmp_path, model_dir, manifest_path)
    adapter.load()
    fake_upstream.created[0]._error = RuntimeError("CUDA out of memory during run")

    with pytest.raises(InferenceError) as excinfo:
        adapter.generate(Image.new("RGBA", (32, 32), (1, 2, 3, 255)), started_at=0.0)

    assert excinfo.value.error_code == GPU_OUT_OF_MEMORY


def test_adapter_requires_the_prepared_rgba_image(tmp_path: Path, fake_upstream) -> None:
    model_dir, manifest_path = _weights(tmp_path)
    adapter = _adapter(tmp_path, model_dir, manifest_path)
    adapter.load()

    with pytest.raises(InferenceError) as excinfo:
        adapter.generate(Image.new("RGB", (32, 32)), started_at=0.0)

    assert excinfo.value.error_code == MODEL_INFERENCE_FAILED


def test_adapter_unload_releases_the_model(tmp_path: Path, fake_upstream) -> None:
    model_dir, manifest_path = _weights(tmp_path)
    adapter = _adapter(tmp_path, model_dir, manifest_path)
    adapter.load()
    assert len(fake_upstream.created) == 1

    adapter.unload()
    adapter.load()

    # The model was released and re-created instead of being reused.
    assert len(fake_upstream.created) == 2
