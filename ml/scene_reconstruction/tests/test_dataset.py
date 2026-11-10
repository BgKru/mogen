"""Dataset preparation and image validation (07 Sections 4.5-4.8)."""

from __future__ import annotations

import io

import pytest
from PIL import Image

from scene_reconstruction.dataset import (
    SourceImage,
    create_workspace,
    inspect_image,
    prepare_dataset,
    workspace_paths,
)
from scene_reconstruction.exceptions import (
    DUPLICATE_IMAGES,
    IMAGE_DECODE_FAILED,
    INSUFFICIENT_IMAGES,
    INVALID_SCENE_DATASET,
    DatasetError,
)

from .helpers import image_bytes


def _sources(count: int, **kwargs: object) -> list[SourceImage]:
    return [
        SourceImage.from_bytes(
            image_bytes(color=(20 * index % 255, 90, 160), **kwargs),
            filename=f"photo_{index}.jpg",
            image_id=f"image-{index}",
        )
        for index in range(count)
    ]


def test_prepares_an_ordered_vocabulary_of_images(tmp_path):
    dataset = prepare_dataset(_sources(5), work_dir=tmp_path, min_images=3, max_images=10)

    assert dataset.image_count == 5
    assert [image.filename for image in dataset.images] == [
        "image_001.jpg",
        "image_002.jpg",
        "image_003.jpg",
        "image_004.jpg",
        "image_005.jpg",
    ]
    assert dataset.formats == {"JPEG": 5}
    assert all(image.path.is_file() for image in dataset.images)
    assert (tmp_path / "images").is_dir()
    assert (tmp_path / "colmap").is_dir()
    assert (tmp_path / "openmvs").is_dir()
    assert (tmp_path / "logs").is_dir()


def test_copies_the_original_bytes_without_reencoding(tmp_path):
    payload = image_bytes(size=(640, 480))
    dataset = prepare_dataset(
        [SourceImage.from_bytes(payload, filename="a.jpg")], work_dir=tmp_path, min_images=1
    )
    assert dataset.images[0].path.read_bytes() == payload


def test_accepts_png(tmp_path):
    dataset = prepare_dataset(
        [SourceImage.from_bytes(image_bytes(fmt="PNG"), filename="a.png")],
        work_dir=tmp_path,
        min_images=1,
    )
    assert dataset.images[0].format == "PNG"
    assert dataset.images[0].filename.endswith(".png")


def test_rejects_too_few_images(tmp_path):
    with pytest.raises(DatasetError) as exc:
        prepare_dataset(_sources(2), work_dir=tmp_path, min_images=3)
    assert exc.value.error_code == INSUFFICIENT_IMAGES


def test_rejects_too_many_images(tmp_path):
    with pytest.raises(DatasetError) as exc:
        prepare_dataset(_sources(4), work_dir=tmp_path, min_images=1, max_images=3)
    assert exc.value.error_code == INVALID_SCENE_DATASET


def test_rejects_exact_duplicates(tmp_path):
    payload = image_bytes()
    sources = [
        SourceImage.from_bytes(payload, filename="a.jpg"),
        SourceImage.from_bytes(payload, filename="b.jpg"),
        SourceImage.from_bytes(image_bytes(color=(1, 2, 3)), filename="c.jpg"),
    ]
    with pytest.raises(DatasetError) as exc:
        prepare_dataset(sources, work_dir=tmp_path, min_images=1)
    assert exc.value.error_code == DUPLICATE_IMAGES


def test_rejects_undecodable_content(tmp_path):
    with pytest.raises(DatasetError) as exc:
        prepare_dataset(
            [SourceImage.from_bytes(b"not an image", filename="broken.jpg")],
            work_dir=tmp_path,
            min_images=1,
        )
    assert exc.value.error_code == IMAGE_DECODE_FAILED


def test_rejects_unsupported_image_format(tmp_path):
    buffer = io.BytesIO()
    Image.new("RGB", (64, 64), (1, 2, 3)).save(buffer, format="GIF")
    with pytest.raises(DatasetError) as exc:
        prepare_dataset(
            [SourceImage.from_bytes(buffer.getvalue(), filename="anim.gif")],
            work_dir=tmp_path,
            min_images=1,
        )
    assert exc.value.error_code == INVALID_SCENE_DATASET


def test_rejects_images_above_the_dimension_limit(tmp_path):
    with pytest.raises(DatasetError) as exc:
        prepare_dataset(
            [SourceImage.from_bytes(image_bytes(size=(400, 300)), filename="big.jpg")],
            work_dir=tmp_path,
            min_images=1,
            max_image_dimension=100,
        )
    assert exc.value.error_code == INVALID_SCENE_DATASET


def test_inspect_image_reports_format_and_dimensions(tmp_path):
    path = tmp_path / "probe.jpg"
    path.write_bytes(image_bytes(size=(321, 123)))
    assert inspect_image(path, max_dimension=1000) == ("JPEG", 321, 123)


def test_workspace_paths_are_task_scoped(tmp_path):
    paths = create_workspace(tmp_path / "task-a")
    assert workspace_paths(tmp_path / "task-a")["images"] == paths["images"]
    assert paths["images"].is_dir()
    assert paths["output"].is_dir()


def test_a_failed_preparation_does_not_leave_the_bad_file(tmp_path):
    with pytest.raises(DatasetError):
        prepare_dataset(
            [
                SourceImage.from_bytes(image_bytes(), filename="ok.jpg"),
                SourceImage.from_bytes(b"broken", filename="bad.jpg"),
            ],
            work_dir=tmp_path,
            min_images=1,
        )
    assert not (tmp_path / "images" / "image_002.upload").exists()
