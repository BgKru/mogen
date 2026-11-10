"""Preflight checks: tools, disk space and dataset re-validation (07 Sections 4.8, 14.4)."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from scene_reconstruction.config import SceneConfig
from scene_reconstruction.dataset import SourceImage, prepare_dataset
from scene_reconstruction.exceptions import (
    EXTERNAL_TOOL_UNAVAILABLE,
    INSUFFICIENT_STORAGE,
    INVALID_SCENE_DATASET,
    DatasetError,
    ResourceError,
    ToolError,
)
from scene_reconstruction.preflight import (
    REQUIRED_TOOLS,
    check_dataset,
    check_disk_space,
    verify_toolchain,
)

from .helpers import image_bytes


def _fake_tool(directory: Path, name: str, *, executable: bool = True) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / name
    path.write_text("#!/bin/sh\necho 'fake tool version 1.0'\nexit 0\n", encoding="utf-8")
    path.chmod(0o755 if executable else 0o644)
    return path


def _config(tmp_path: Path) -> SceneConfig:
    colmap = _fake_tool(tmp_path / "bin", "colmap")
    openmvs = tmp_path / "openmvs"
    for name in REQUIRED_TOOLS:
        if name != "colmap":
            _fake_tool(openmvs, name)
    return SceneConfig(colmap_executable=colmap, openmvs_bin_dir=openmvs)


def test_verifies_every_required_tool(tmp_path):
    report = verify_toolchain(_config(tmp_path))
    assert report.verified is True
    assert set(report.as_dict()) == set(REQUIRED_TOOLS)
    assert all("fake" in version for version in report.as_dict().values())


def test_tool_probes_do_not_leave_logs_in_the_process_directory(tmp_path, monkeypatch):
    """OpenMVS writes a log on every start; the probe must not pollute the CWD.

    Traceability: 07 Section 15.7 (temporary storage must not grow
    uncontrolled), roadmap 8.5. Without a scratch directory each worker restart
    left one log file per OpenMVS tool in ``/app``.
    """
    config = _config(tmp_path)
    for name in REQUIRED_TOOLS:
        if name == "colmap":
            continue
        tool = config.openmvs_bin_dir / name
        tool.write_text(
            "#!/bin/sh\n"
            'echo "probe" > "$PWD/${0##*/}-probe.log"\n'
            "echo 'fake tool version 1.0'\n"
            "exit 1\n",
            encoding="utf-8",
        )
        tool.chmod(0o755)
    working_directory = tmp_path / "cwd"
    working_directory.mkdir()
    monkeypatch.chdir(working_directory)

    report = verify_toolchain(config)

    assert report.verified is True
    assert list(working_directory.iterdir()) == []


def test_missing_tool_is_reported(tmp_path):
    config = _config(tmp_path)
    (config.openmvs_bin_dir / "RefineMesh").unlink()
    with pytest.raises(ToolError) as exc:
        verify_toolchain(config)
    assert exc.value.error_code == EXTERNAL_TOOL_UNAVAILABLE


def test_non_executable_tool_is_reported(tmp_path):
    config = _config(tmp_path)
    path = config.openmvs_bin_dir / "TextureMesh"
    path.chmod(0o644)
    with pytest.raises(ToolError):
        verify_toolchain(config)


def test_disk_space_check_passes_and_fails(tmp_path):
    assert check_disk_space(tmp_path, min_free_bytes=1) > 0
    with pytest.raises(ResourceError) as exc:
        check_disk_space(tmp_path, min_free_bytes=10**18)
    assert exc.value.error_code == INSUFFICIENT_STORAGE


def test_dataset_check_rejects_duplicates(tmp_path):
    dataset = prepare_dataset(
        [SourceImage.from_bytes(image_bytes(), filename="a.jpg")],
        work_dir=tmp_path,
        min_images=1,
    )
    broken = replace(dataset, duplicates=("a.jpg", "b.jpg"))
    with pytest.raises(DatasetError) as exc:
        check_dataset(broken, SceneConfig())
    assert exc.value.error_code == INVALID_SCENE_DATASET


def test_dataset_check_rejects_a_missing_workspace_file(tmp_path):
    dataset = prepare_dataset(
        [SourceImage.from_bytes(image_bytes(), filename="a.jpg")],
        work_dir=tmp_path,
        min_images=1,
    )
    dataset.images[0].path.unlink()
    with pytest.raises(DatasetError):
        check_dataset(dataset, SceneConfig())
