"""Pipeline orchestration with a fake model (no GPU required).

The real-model integration test lives in ``test_real_inference.py`` and is
gated by ``RUN_REAL_MODEL_TESTS=1`` (TEST-AC-12); these tests keep ordinary CI
fast and deterministic.
"""

from __future__ import annotations

import io
import json
from pathlib import Path

import pytest
from image_quality import ImageQualityConfig
from PIL import Image

import object_generation.pipeline as pipeline_module
from object_generation.config import ObjectGenerationConfig
from object_generation.exceptions import InferenceError, ObjectGenerationError
from object_generation.generator import GeneratedMesh
from object_generation.mesh_processor import validate_mesh
from object_generation.pipeline import (
    STAGES,
    PipelineCallbacks,
    run_object_generation,
)
from object_generation.preprocessing import decode_image
from tests.helpers import colored_box


def _config(tmp_path: Path, **overrides) -> ObjectGenerationConfig:
    values = {
        "model_dir": tmp_path / "model",
        "model_revision": "test",
        "model_sha256": "",
        "remove_background": False,
        "device": "cpu",
    }
    values.update(overrides)
    return ObjectGenerationConfig(**values)


def _png_bytes(size: tuple[int, int] = (64, 64)) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", size, color=(120, 80, 40)).save(buffer, format="PNG")
    return buffer.getvalue()


class FakeGenerator:
    def __init__(self, mesh=None) -> None:
        self._mesh = mesh or colored_box()

    def generate(self, image, *, started_at=None) -> GeneratedMesh:
        assert image.size == (512, 512)
        stats = validate_mesh(self._mesh)
        return GeneratedMesh(
            mesh=self._mesh,
            stats=stats,
            inference_seconds=0.01,
            extraction_seconds=0.02,
        )


class FailingGenerator:
    def generate(self, image, *, started_at=None):
        raise InferenceError("GPU_OUT_OF_MEMORY", "CUDA out of memory")


def test_the_pipeline_reports_real_stages_and_exports_a_validated_glb(
    tmp_path: Path,
) -> None:
    stages: list[str] = []
    heartbeats: list[int] = []
    original = _png_bytes()

    asset = run_object_generation(
        image_bytes=original,
        config=_config(tmp_path),
        work_dir=tmp_path / "task",
        callbacks=PipelineCallbacks(
            report_stage=lambda stage, _message: stages.append(stage),
            heartbeat=lambda: heartbeats.append(1),
        ),
        generator=FakeGenerator(),
    )

    assert stages == list(STAGES)
    assert len(heartbeats) >= len(STAGES)
    assert asset.path.is_file()
    assert asset.path.name == "model.glb"
    assert asset.format == "GLB"
    assert asset.mime_type == "model/gltf-binary"
    assert asset.file_size_bytes > 0
    assert len(asset.sha256) == 64
    assert asset.metadata["has_vertex_colors"] is True
    assert asset.metadata["vertices_count"] > 0
    assert asset.metadata["faces_count"] > 0
    assert asset.metadata["generation"]["bake_texture"] is False
    # The original upload is preserved byte-for-byte (OBJ-AC-05).
    assert (tmp_path / "task" / "input" / "original.png").read_bytes() == original
    assert (tmp_path / "task" / "input" / "preprocessed.png").is_file()
    assert (tmp_path / "task" / "run.json").is_file()


def test_a_preprocessing_failure_stops_before_inference(tmp_path: Path) -> None:
    stages: list[str] = []

    with pytest.raises(Exception) as excinfo:
        run_object_generation(
            image_bytes=b"not an image",
            config=_config(tmp_path),
            work_dir=tmp_path / "task",
            callbacks=PipelineCallbacks(report_stage=lambda stage, _message: stages.append(stage)),
            generator=FakeGenerator(),
        )

    assert excinfo.value.error_code == "IMAGE_DECODE_FAILED"
    assert stages == ["IMAGE_PREPARATION"]
    # A file rejected by the existing decoder never reaches the analyzer, so it
    # cannot be misreported as a quality finding.
    manifest = json.loads((tmp_path / "task" / "run.json").read_text(encoding="utf-8"))
    assert "image_quality" not in manifest


def test_an_inference_failure_is_propagated_with_its_code(tmp_path: Path) -> None:
    with pytest.raises(InferenceError) as excinfo:
        run_object_generation(
            image_bytes=_png_bytes(),
            config=_config(tmp_path),
            work_dir=tmp_path / "task",
            generator=FailingGenerator(),
        )

    assert excinfo.value.error_code == "GPU_OUT_OF_MEMORY"
    assert (tmp_path / "task" / "run.json").is_file()


def test_cancellation_between_stages_stops_the_pipeline(tmp_path: Path) -> None:
    class Stop:
        def __call__(self) -> None:
            raise RuntimeError("stop requested")

    with pytest.raises(RuntimeError):
        run_object_generation(
            image_bytes=_png_bytes(),
            config=_config(tmp_path),
            work_dir=tmp_path / "task",
            callbacks=PipelineCallbacks(raise_if_cancelled=Stop()),
            generator=FakeGenerator(),
        )


# -- advisory image-quality analysis (11_image_quality_analysis.md) ----------


def test_quality_analysis_inspects_the_decoded_original_before_inference(
    tmp_path: Path, monkeypatch
) -> None:
    order: list[str] = []
    observed: dict[str, object] = {}
    real_analyze = pipeline_module.analyze_image

    def spy(image, *, image_id, filename, config):
        observed["size"] = image.size
        observed["pixels"] = image.tobytes()
        observed["image_id"] = image_id
        observed["filename"] = filename
        order.append("quality")
        return real_analyze(image, image_id=image_id, filename=filename, config=config)

    monkeypatch.setattr(pipeline_module, "analyze_image", spy)

    class OrderingGenerator(FakeGenerator):
        def generate(self, image, *, started_at=None) -> GeneratedMesh:
            order.append("inference")
            return super().generate(image, started_at=started_at)

    original = _png_bytes()
    decoded, _source_format = decode_image(original)

    asset = run_object_generation(
        image_bytes=original,
        config=_config(tmp_path),
        work_dir=tmp_path / "task",
        generator=OrderingGenerator(),
        image_id="task-1",
        filename="photo.png",
    )

    # The analyzer saw the decoded original (64x64), not the 512 px model input,
    # and it ran before inference and background removal.
    assert order == ["quality", "inference"]
    assert observed["size"] == (64, 64)
    assert observed["pixels"] == decoded.tobytes()
    assert observed["image_id"] == "task-1"
    assert observed["filename"] == "photo.png"
    assert asset.metadata["image_quality"]["status"] == "OK"
    manifest = json.loads((tmp_path / "task" / "run.json").read_text(encoding="utf-8"))
    assert manifest["image_quality"]["report"]["filename"] == "photo.png"
    assert manifest["image_quality"]["report"]["width"] == 64


def test_disabling_quality_analysis_preserves_the_manifest(tmp_path: Path) -> None:
    asset = run_object_generation(
        image_bytes=_png_bytes(),
        config=_config(tmp_path, image_quality=ImageQualityConfig(enabled=False)),
        work_dir=tmp_path / "task",
        generator=FakeGenerator(),
    )

    manifest = json.loads((tmp_path / "task" / "run.json").read_text(encoding="utf-8"))
    assert "image_quality" not in manifest
    assert "image_quality" not in asset.metadata
    assert asset.metadata["has_vertex_colors"] is True


def test_advisory_quality_failure_is_recorded_and_generation_continues(
    tmp_path: Path, monkeypatch
) -> None:
    def broken(*_args, **_kwargs):
        raise RuntimeError("analyzer crashed")

    monkeypatch.setattr(pipeline_module, "analyze_image", broken)

    asset = run_object_generation(
        image_bytes=_png_bytes(),
        config=_config(tmp_path),
        work_dir=tmp_path / "task",
        generator=FakeGenerator(),
    )

    section = asset.metadata["image_quality"]
    assert section == {
        "status": "UNAVAILABLE",
        "error_code": "QUALITY_ANALYSIS_UNAVAILABLE",
    }
    manifest = json.loads((tmp_path / "task" / "run.json").read_text(encoding="utf-8"))
    assert manifest["image_quality"] == section
    assert (tmp_path / "task" / "input" / "preprocessed.png").is_file()


def test_required_quality_failure_stops_before_preprocessing(tmp_path: Path, monkeypatch) -> None:
    def broken(*_args, **_kwargs):
        raise RuntimeError("analyzer crashed")

    monkeypatch.setattr(pipeline_module, "analyze_image", broken)

    class NeverGenerator:
        def generate(self, *_args, **_kwargs) -> GeneratedMesh:
            raise AssertionError("inference must not run")

    with pytest.raises(ObjectGenerationError) as excinfo:
        run_object_generation(
            image_bytes=_png_bytes(),
            config=_config(tmp_path, image_quality=ImageQualityConfig(required=True)),
            work_dir=tmp_path / "task",
            generator=NeverGenerator(),
        )

    assert excinfo.value.error_code == "QUALITY_ANALYSIS_FAILED"
    assert not (tmp_path / "task" / "input" / "preprocessed.png").exists()
    manifest = json.loads((tmp_path / "task" / "run.json").read_text(encoding="utf-8"))
    assert manifest["stages"] == []


# -- generator contract and fallback (13_advanced_object_generation.md) -------


def test_textured_generator_metadata_is_recorded(tmp_path: Path) -> None:
    from object_generation.generator_base import GeneratorResult, PreprocessingCapabilities
    from tests.helpers import textured_box

    class TexturedGenerator:
        name = "sf3d"
        revision = "ff21fc49"
        model_id = "stabilityai/stable-fast-3d"
        model_revision = "f0c9a8ff"

        def capabilities(self) -> PreprocessingCapabilities:
            return PreprocessingCapabilities(
                mode="rgba_foreground",
                background_removal=False,
                alpha=True,
                foreground_crop=True,
                foreground_ratio=True,
                input_size=None,
                color_mode="RGBA",
            )

        def generate(self, image, *, started_at: float) -> GeneratorResult:
            # The pipeline must pass the RGBA foreground, not the 512 px composite.
            assert image.mode == "RGBA"
            return GeneratorResult(
                mesh=textured_box(texture_size=32),
                name=self.name,
                revision=self.revision,
                model_id=self.model_id,
                model_revision=self.model_revision,
                inference_seconds=0.5,
                postprocessing_seconds=0.1,
                has_textures=True,
                texture_resolution=32,
                diagnostics={"preprocessing_profile": "sf3d_default"},
            )

    asset = run_object_generation(
        image_bytes=_png_bytes(),
        config=_config(tmp_path, remove_background=False),
        work_dir=tmp_path / "task",
        generator=TexturedGenerator(),
    )

    generator = asset.metadata["generator"]
    assert generator["name"] == "sf3d"
    assert generator["model_revision"] == "f0c9a8ff"
    assert generator["inference_seconds"] == 0.5
    assert generator["has_textures"] is True
    assert generator["texture_resolution"] == 32
    assert generator["diagnostics"]["preprocessing_profile"] == "sf3d_default"
    assert generator["preprocessing_capabilities"]["mode"] == "rgba_foreground"
    assert generator["normalization"]["has_textures"] is True
    assert "peak_cuda_allocated_bytes" not in generator
    assert asset.metadata["has_textures"] is True
    assert asset.metadata["textures_count"] >= 1
    assert asset.metadata["timing"]["postprocessing_seconds"] == 0.1

    manifest = json.loads((tmp_path / "task" / "run.json").read_text(encoding="utf-8"))
    assert manifest["generator"]["name"] == "sf3d"
    assert manifest["preprocessing"]["input_mode"] == "rgba_foreground"


def test_pre_inference_fallback_to_triposr_is_recorded(tmp_path: Path, monkeypatch) -> None:
    from object_generation.config import SF3DConfig
    from object_generation.exceptions import (
        GENERATOR_NOT_AVAILABLE,
        GeneratorUnavailableError,
    )

    class TripoSRFallback(FakeGenerator):
        name = "triposr"
        revision = "d26e3318"
        model_id = "stabilityai/TripoSR"
        model_revision = "5b521936"

    def fake_create(config, *, load=True):
        if config.generator == "sf3d":
            raise GeneratorUnavailableError(GENERATOR_NOT_AVAILABLE, "weights unavailable")
        return TripoSRFallback()

    monkeypatch.setattr(pipeline_module, "create_generator", fake_create)

    config = _config(
        tmp_path,
        generator="sf3d",
        generator_fallback=True,
        sf3d=SF3DConfig(
            enabled=True,
            model_revision="f0c9a8ff",
            model_dir=tmp_path / "sf3d",
            manifest_path=tmp_path / "sf3d" / "manifest.json",
        ),
    )

    asset = run_object_generation(
        image_bytes=_png_bytes(),
        config=config,
        work_dir=tmp_path / "task",
    )

    fallback = asset.metadata["generator"]["fallback"]
    assert fallback == {
        "used": True,
        "reason": GENERATOR_NOT_AVAILABLE,
        "requested_generator": "sf3d",
        "actual_generator": "triposr",
    }
    assert asset.metadata["generator"]["name"] == "triposr"
    assert asset.metadata["generation"]["generator"] == "sf3d"


def test_fallback_is_not_used_when_disabled(tmp_path: Path, monkeypatch) -> None:
    from object_generation.config import SF3DConfig
    from object_generation.exceptions import (
        GENERATOR_NOT_AVAILABLE,
        GeneratorUnavailableError,
    )

    def fake_create(config, *, load=True):
        raise GeneratorUnavailableError(GENERATOR_NOT_AVAILABLE, "weights unavailable")

    monkeypatch.setattr(pipeline_module, "create_generator", fake_create)

    config = _config(
        tmp_path,
        generator="sf3d",
        generator_fallback=False,
        sf3d=SF3DConfig(
            enabled=True,
            model_revision="f0c9a8ff",
            model_dir=tmp_path / "sf3d",
            manifest_path=tmp_path / "sf3d" / "manifest.json",
        ),
    )

    with pytest.raises(GeneratorUnavailableError):
        run_object_generation(
            image_bytes=_png_bytes(),
            config=config,
            work_dir=tmp_path / "task",
        )


def test_background_removal_runs_exactly_once_for_rgba_generators(
    tmp_path: Path, monkeypatch
) -> None:
    """13 Section 5.4: the adapter must not repeat the shared preprocessing."""
    import object_generation.preprocessing as preprocessing_module
    from object_generation.generator_base import GeneratorResult, PreprocessingCapabilities
    from tests.helpers import textured_box

    calls = {"rembg": 0, "rgba": 0, "rgb": 0}
    real_rgba = pipeline_module.prepare_rgba_input

    def spy_rgba(*args, **kwargs):
        calls["rgba"] += 1
        return real_rgba(*args, **kwargs)

    def spy_remove_background(image, _session):
        calls["rembg"] += 1
        return image.convert("RGBA")

    def forbidden_rgb(*_args, **_kwargs):
        calls["rgb"] += 1
        raise AssertionError("the TripoSR preprocessing path must not run for SF3D")

    monkeypatch.setattr(pipeline_module, "prepare_rgba_input", spy_rgba)
    monkeypatch.setattr(pipeline_module, "prepare_model_input", forbidden_rgb)
    monkeypatch.setattr(pipeline_module, "get_rembg_session", lambda _model: object())
    monkeypatch.setattr(preprocessing_module, "remove_background", spy_remove_background)

    class RgbaGenerator:
        name = "sf3d"
        revision = "test"
        model_id = "sf3d"
        model_revision = "test"

        def capabilities(self) -> PreprocessingCapabilities:
            return PreprocessingCapabilities(
                mode="rgba_foreground",
                background_removal=True,
                alpha=True,
                foreground_crop=True,
                foreground_ratio=True,
                input_size=None,
                color_mode="RGBA",
            )

        def generate(self, image, *, started_at: float) -> GeneratorResult:
            assert image.mode == "RGBA"
            return GeneratorResult(
                mesh=textured_box(),
                name=self.name,
                revision=self.revision,
                model_id=self.model_id,
                model_revision=self.model_revision,
                inference_seconds=0.0,
                has_textures=True,
                texture_resolution=64,
            )

    run_object_generation(
        image_bytes=_png_bytes(),
        config=_config(tmp_path, remove_background=True),
        work_dir=tmp_path / "task",
        generator=RgbaGenerator(),
    )

    assert calls == {"rembg": 1, "rgba": 1, "rgb": 0}


# -- mesh/texture enhancement (14_mesh_texture_enhancement.md) --------------


def test_default_enhancement_adds_normals_and_metadata(tmp_path: Path) -> None:
    asset = run_object_generation(
        image_bytes=_png_bytes(),
        config=_config(tmp_path),
        work_dir=tmp_path / "task",
        generator=FakeGenerator(),
    )

    enhancement = asset.metadata["enhancement"]
    assert enhancement["scope"] == "object"
    assert enhancement["operations"] == ["mesh_cleanup", "normal_correction"]
    assert enhancement["normal_export"] is True
    assert enhancement["before"]["vertices_count"] > 0
    assert enhancement["after"]["has_normals"] is True
    assert asset.metadata["glb_validation"]["has_normals"] is True


def test_baked_texture_setting_produces_a_self_contained_textured_glb(tmp_path: Path) -> None:
    from object_generation.enhancement import EnhancementConfig

    config = _config(
        tmp_path,
        bake_texture=True,
        texture_resolution=128,
        enhancement=EnhancementConfig(bake_texture=True, texture_resolution=128),
    )

    asset = run_object_generation(
        image_bytes=_png_bytes(),
        config=config,
        work_dir=tmp_path / "task",
        generator=FakeGenerator(),
    )

    enhancement = asset.metadata["enhancement"]
    assert "uv_generation" in enhancement["operations"]
    assert "texture_baking" in enhancement["operations"]
    assert enhancement["baking"]["resolution"] == 128
    assert enhancement["appearance_mode"] == "texture"
    assert asset.metadata["has_textures"] is True
    assert asset.metadata["generation"]["bake_texture"] is True
    manifest = json.loads((tmp_path / "task" / "run.json").read_text(encoding="utf-8"))
    assert manifest["enhancement"]["baking"]["resolution"] == 128
    assert manifest["enhancement"]["manifest"]["dependencies"]["trimesh"]
