"""Shared fixtures for the scene-reconstruction unit tests."""

from __future__ import annotations

import io
import sqlite3
import struct
from pathlib import Path

import numpy as np
import trimesh
from PIL import Image

from scene_reconstruction.config import SceneConfig


def image_bytes(
    *,
    size: tuple[int, int] = (800, 600),
    color: tuple[int, int, int] = (120, 90, 60),
    fmt: str = "JPEG",
) -> bytes:
    """Return a real decodable JPEG/PNG image."""
    buffer = io.BytesIO()
    Image.new("RGB", size, color).save(buffer, format=fmt)
    return buffer.getvalue()


def gradient_image_bytes(*, size: tuple[int, int] = (1024, 768), seed: int = 0) -> bytes:
    """Return a deterministic, visually non-uniform JPEG.

    Feature extraction needs texture; a flat colour would be a poor fixture.
    """
    rng = np.random.default_rng(seed)
    array = rng.integers(0, 255, size=(size[1], size[0], 3), dtype=np.uint8)
    buffer = io.BytesIO()
    Image.fromarray(array, mode="RGB").save(buffer, format="JPEG", quality=90)
    return buffer.getvalue()


def recompressed_jpeg(data: bytes, *, scale: float = 0.6, quality: int = 60) -> bytes:
    """Return a resized and recompressed copy of an encoded image.

    The bytes differ from the original (so the SHA-256 duplicate check accepts
    both), while the pixels remain perceptually similar.
    """
    with Image.open(io.BytesIO(data)) as opened:
        opened.load()
        width = max(1, int(opened.width * scale))
        height = max(1, int(opened.height * scale))
        resized = opened.convert("RGB").resize((width, height))
    buffer = io.BytesIO()
    resized.save(buffer, format="JPEG", quality=quality)
    return buffer.getvalue()


def textured_png(path: Path, size: int = 64) -> Path:
    """Write a small checkerboard texture."""
    array = np.zeros((size, size, 3), dtype=np.uint8)
    for y in range(size):
        for x in range(size):
            if (x // 8 + y // 8) % 2 == 0:
                array[y, x] = (180, 120, 70)
            else:
                array[y, x] = (60, 90, 140)
    Image.fromarray(array, mode="RGB").save(path, format="PNG")
    return path


def textured_quad_obj(directory: Path, *, name: str = "scene") -> Path:
    """Write a 3D OBJ/MTL/PNG set that trimesh loads with a texture."""
    directory.mkdir(parents=True, exist_ok=True)
    box = trimesh.creation.box(extents=(1.0, 1.0, 1.0))
    uv = np.array([[0.0, 0.0], [1.0, 0.0], [1.0, 1.0], [0.0, 1.0]] * 2)[: len(box.vertices)]
    image = Image.frombytes("RGB", (16, 16), bytes([200, 120, 60] * (16 * 16)))
    material = trimesh.visual.material.PBRMaterial(
        baseColorTexture=image, metallicFactor=0.0, roughnessFactor=1.0
    )
    visuals = trimesh.visual.TextureVisuals(uv=uv, material=material)
    mesh = trimesh.Trimesh(vertices=box.vertices, faces=box.faces, visual=visuals, process=False)
    path = directory / f"{name}.obj"
    mesh.export(str(path), file_type="obj")
    return path


def textured_glb(path: Path, *, include_normals: bool = False) -> Path:
    """Write a self-contained textured GLB built with trimesh."""
    path.parent.mkdir(parents=True, exist_ok=True)
    box = trimesh.creation.box(extents=(1.0, 1.0, 0.5))
    uv = np.array([[0.0, 0.0], [1.0, 0.0], [1.0, 1.0], [0.0, 1.0]] * 2)[: len(box.vertices)]
    image = Image.frombytes("RGB", (32, 32), bytes([200, 120, 60] * (32 * 32)))
    material = trimesh.visual.material.PBRMaterial(
        baseColorTexture=image, metallicFactor=0.0, roughnessFactor=1.0
    )
    visuals = trimesh.visual.TextureVisuals(uv=uv, material=material)
    mesh = trimesh.Trimesh(vertices=box.vertices, faces=box.faces, visual=visuals, process=False)
    scene = trimesh.Scene(mesh)
    scene.export(str(path), file_type="glb", include_normals=include_normals)
    return path


def write_sparse_model(
    text_dir: Path,
    *,
    camera_count: int = 1,
    images: list[tuple[int, float]] | None = None,
    points: list[tuple[int, float, list[int]]] | None = None,
    width: int = 1600,
    height: int = 1200,
) -> Path:
    """Write COLMAP TXT model files with deterministic content."""
    text_dir.mkdir(parents=True, exist_ok=True)
    cameras = [
        f"{index + 1} SIMPLE_RADIAL {width} {height} 1500.0 800.0 600.0 0.01"
        for index in range(camera_count)
    ]
    (text_dir / "cameras.txt").write_text(
        "# Camera list\n" + "\n".join(cameras) + "\n", encoding="utf-8"
    )
    images = [(1, 0.001)] if images is None else images
    image_lines = ["# Image list"]
    for image_id, _error in images:
        image_lines.append(f"{image_id} 1.0 0.0 0.0 0.0 0.0 0.0 0.0 1 image_{image_id:03d}.jpg")
        image_lines.append("")
    (text_dir / "images.txt").write_text("\n".join(image_lines), encoding="utf-8")
    points = [(1, 0.5, [1])] if points is None else points
    point_lines = ["# 3D point list with one line per point"]
    for point_id, error, tracks in points:
        track = " ".join(f"{image_id} 0" for image_id in tracks)
        point_lines.append(f"{point_id} 0.0 0.0 0.0 255 255 255 {error} {track}")
    (text_dir / "points3D.txt").write_text("\n".join(point_lines) + "\n", encoding="utf-8")
    return text_dir


def create_colmap_database(
    path: Path,
    images: int = 3,
    verified_pairs: list[tuple[int, int]] | None = None,
) -> None:
    """Create a minimal COLMAP-like SQLite database for runner tests."""
    connection = sqlite3.connect(path)
    try:
        connection.executescript(
            """
            DROP TABLE IF EXISTS images;
            DROP TABLE IF EXISTS keypoints;
            DROP TABLE IF EXISTS matches;
            DROP TABLE IF EXISTS two_view_geometries;
            CREATE TABLE images (image_id INTEGER PRIMARY KEY, name TEXT);
            CREATE TABLE keypoints (image_id INTEGER, rows INTEGER);
            CREATE TABLE matches (pair_id INTEGER, rows INTEGER);
            CREATE TABLE two_view_geometries (
                pair_id INTEGER,
                rows INTEGER,
                image_id1 INTEGER,
                image_id2 INTEGER
            );
            """
        )
        connection.executemany(
            "INSERT INTO images (image_id, name) VALUES (?, ?)",
            [(index, f"image_{index:03d}.jpg") for index in range(1, images + 1)],
        )
        connection.executemany(
            "INSERT INTO keypoints (image_id, rows) VALUES (?, ?)",
            [(index, 500) for index in range(1, images + 1)],
        )
        pairs = (
            verified_pairs
            if verified_pairs is not None
            else [(left, left + 1) for left in range(1, images)]
        )
        connection.executemany(
            "INSERT INTO two_view_geometries "
            "(pair_id, rows, image_id1, image_id2) VALUES (?, ?, ?, ?)",
            [(index, 120, left, right) for index, (left, right) in enumerate(pairs, start=1)],
        )
        connection.commit()
    finally:
        connection.close()


def write_ply_points(path: Path, vertices: int = 500) -> Path:
    """Write a PLY header with the requested vertex count."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(
        b"ply\nformat binary_little_endian 1.0\n"
        + f"element vertex {vertices}\n".encode()
        + b"property float x\nproperty float y\nproperty float z\nend_header\n"
        + b"\x00" * (vertices * 12)
    )
    return path


def write_mesh_ply(path: Path) -> Path:
    """Write a real triangulated PLY mesh."""
    path.parent.mkdir(parents=True, exist_ok=True)
    mesh = trimesh.creation.box(extents=(1.0, 1.0, 1.0))
    mesh.export(str(path), file_type="ply")
    return path


def write_raw_glb(path: Path) -> Path:
    """Write a GLB for the conversion-tool output fixture."""
    path.parent.mkdir(parents=True, exist_ok=True)
    scene = trimesh.Scene(trimesh.creation.box(extents=(1.0, 1.0, 1.0)))
    scene.export(str(path), file_type="glb")
    return path


def default_config(**overrides: object) -> SceneConfig:
    """Return a predictable configuration for tests."""
    values: dict[str, object] = {
        "colmap_use_gpu": False,
        "max_threads": 1,
        "min_registered_images": 2,
        "min_registration_ratio": 0.5,
        "min_sparse_points": 1,
        "min_dense_points": 1,
        "stage_timeouts": {},
    }
    values.update(overrides)
    return SceneConfig(**values)  # type: ignore[arg-type]


def glb_chunk_lengths(data: bytes) -> tuple[int, int]:
    """Return the JSON and BIN chunk lengths of a GLB."""
    offset = 12
    lengths: list[int] = []
    while offset < len(data):
        length, _kind = struct.unpack_from("<II", data, offset)
        lengths.append(length)
        offset += 8 + length
    return lengths[0], lengths[1] if len(lengths) > 1 else 0
