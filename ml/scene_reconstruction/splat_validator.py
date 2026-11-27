"""Independent Gaussian-splat PLY validation (15 Sections 5.3 and 10.1).

The exporter is not trusted: this module parses the binary PLY it produced and
checks the exact Nerfstudio 1.1.5 ``ns-export gaussian-splat`` dialect, finite
values, Gaussian-count/size bounds and plausible Gaussian parameters before the
worker is allowed to register a result.

The parser is independent of the exporter implementation and reads in bounded
chunks, so a large artifact cannot be validated by first loading it twice into
memory.
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, BinaryIO

import numpy as np

from .exceptions import SPLAT_ARTIFACT_TOO_LARGE, SPLAT_PLY_INVALID, SplatError
from .splat_config import F_REST_PER_DEGREE, splat_ply_properties

PLY_MAGIC = b"ply"
PLY_FORMAT = "binary_little_endian"
PLY_VERSION = "1.0"
_HEADER_MAX_BYTES = 64 * 1024
_READ_CHUNK_ROWS = 262_144
# Plausible parameter ranges. These are deliberately wide: they reject corrupt
# or mislabelled data (NaN, zeroed transforms, absurd log-scales) without
# second-guessing a trained model's actual values.
_MAX_ABS_POSITION = 1.0e7
_MIN_LOG_SCALE = -30.0
_MAX_LOG_SCALE = 30.0
_MIN_LOGIT_OPACITY = -40.0
_MAX_LOGIT_OPACITY = 40.0
_MIN_QUATERNION_NORM = 1.0e-6
_MAX_QUATERNION_NORM = 1.0e6


@dataclass(frozen=True, slots=True)
class SplatPlyHeader:
    """The parsed header of a binary PLY file."""

    properties: tuple[str, ...]
    vertex_count: int
    data_offset: int
    comments: tuple[str, ...] = ()

    @property
    def bytes_per_vertex(self) -> int:
        return 4 * len(self.properties)

    @property
    def sh_degree(self) -> int:
        """Infer the spherical-harmonic degree from the ``f_rest`` count."""
        rest = sum(1 for name in self.properties if name.startswith("f_rest_"))
        for degree, expected in F_REST_PER_DEGREE.items():
            if rest == expected:
                return degree
        raise SplatError(SPLAT_PLY_INVALID, "The Gaussian PLY has an unsupported SH layout.")


@dataclass(slots=True)
class SplatPlyValidation:
    """Facts measured by the independent validator."""

    path: Path
    sha256: str
    file_size_bytes: int
    gaussian_count: int
    sh_degree: int
    properties: tuple[str, ...]
    bounding_box: dict[str, list[float]] = field(default_factory=dict)
    scale_log_min: float = 0.0
    scale_log_max: float = 0.0
    opacity_logit_min: float = 0.0
    opacity_logit_max: float = 0.0
    quaternion_norm_min: float = 0.0
    warnings: list[str] = field(default_factory=list)

    def as_metadata(self) -> dict[str, Any]:
        """Return the compact, path-free metadata persisted with the result."""
        return {
            "format": "PLY",
            "schema": "nerfstudio_gaussian_splat_v1",
            "sh_degree": self.sh_degree,
            "gaussian_count": self.gaussian_count,
            "file_size_bytes": self.file_size_bytes,
            "sha256": self.sha256,
            "properties": list(self.properties),
            "bounding_box": self.bounding_box,
            "scale_log_range": [round(self.scale_log_min, 6), round(self.scale_log_max, 6)],
            "opacity_logit_range": [
                round(self.opacity_logit_min, 6),
                round(self.opacity_logit_max, 6),
            ],
            "quaternion_norm_min": round(self.quaternion_norm_min, 6),
            "warnings": sorted(set(self.warnings)),
        }


def _read_header(handle: BinaryIO) -> SplatPlyHeader:
    """Read and validate the binary PLY header, returning the data offset."""
    handle.seek(0)
    raw = handle.read(_HEADER_MAX_BYTES)
    marker = raw.find(b"end_header\n")
    if marker < 0:
        marker = raw.find(b"end_header\r\n")
        if marker < 0:
            raise SplatError(SPLAT_PLY_INVALID, "The Gaussian PLY header is incomplete.")
        offset = marker + len(b"end_header\r\n")
    else:
        offset = marker + len(b"end_header\n")

    lines = raw[:offset].decode("ascii", errors="replace").splitlines()
    if not lines or lines[0].strip() != PLY_MAGIC.decode():
        raise SplatError(SPLAT_PLY_INVALID, "The asset is not a PLY file.")
    if len(lines) < 3 or lines[1].split() != ["format", PLY_FORMAT, PLY_VERSION]:
        raise SplatError(
            SPLAT_PLY_INVALID, "The Gaussian PLY must use binary little-endian format 1.0."
        )

    properties: list[str] = []
    vertex_count: int | None = None
    comments: list[str] = []
    seen_end = False
    for line in lines[2:]:
        stripped = line.strip()
        if stripped == "end_header":
            seen_end = True
            break
        if not stripped:
            continue
        if stripped.startswith("comment"):
            comments.append(stripped[len("comment") :].strip())
            continue
        parts = stripped.split()
        if parts[0] == "element":
            if len(parts) != 3 or not parts[2].isdigit():
                raise SplatError(SPLAT_PLY_INVALID, "The Gaussian PLY element is malformed.")
            if parts[1] != "vertex":
                raise SplatError(
                    SPLAT_PLY_INVALID, "A Gaussian-splat PLY must contain a vertex element."
                )
            vertex_count = int(parts[2])
            continue
        if parts[0] == "property":
            if len(parts) != 3:
                raise SplatError(SPLAT_PLY_INVALID, "The Gaussian PLY property is malformed.")
            if parts[1] != "float":
                raise SplatError(SPLAT_PLY_INVALID, "Gaussian-splat properties must be float32.")
            properties.append(parts[2])
            continue
        raise SplatError(SPLAT_PLY_INVALID, "The Gaussian PLY header contains an unknown line.")

    if not seen_end or vertex_count is None:
        raise SplatError(SPLAT_PLY_INVALID, "The Gaussian PLY header is incomplete.")
    if vertex_count < 1:
        raise SplatError(SPLAT_PLY_INVALID, "The Gaussian PLY contains no Gaussians.")
    if not properties:
        raise SplatError(SPLAT_PLY_INVALID, "The Gaussian PLY declares no vertex properties.")
    return SplatPlyHeader(
        properties=tuple(properties),
        vertex_count=vertex_count,
        data_offset=offset,
        comments=tuple(comments),
    )


def _chunks(handle: BinaryIO, header: SplatPlyHeader) -> Iterator[np.ndarray]:
    """Yield ``(rows, properties)`` float32 blocks in bounded chunks."""
    dtype = np.dtype([(name, "<f4") for name in header.properties])
    remaining = header.vertex_count
    while remaining > 0:
        rows = min(_READ_CHUNK_ROWS, remaining)
        raw = handle.read(rows * header.bytes_per_vertex)
        if len(raw) != rows * header.bytes_per_vertex:
            raise SplatError(SPLAT_PLY_INVALID, "The Gaussian PLY data is truncated.")
        block = np.frombuffer(raw, dtype=dtype)
        if block.shape[0] != rows:
            raise SplatError(SPLAT_PLY_INVALID, "The Gaussian PLY data is malformed.")
        yield block
        remaining -= rows


def validate_splat_ply(
    path: Path,
    *,
    sh_degree: int | None = None,
    max_artifact_bytes: int = 512 * 1024 * 1024,
    max_gaussians: int = 5_000_000,
) -> SplatPlyValidation:
    """Validate one Gaussian PLY independently and return its measured facts.

    Raises :class:`SplatError` with ``SPLAT_PLY_INVALID`` or
    ``SPLAT_ARTIFACT_TOO_LARGE``; a partial or wrong-dialect asset is never
    accepted.
    """
    target = Path(path)
    if not target.is_file():
        raise SplatError(SPLAT_PLY_INVALID, "The Gaussian PLY is missing.")
    file_size = target.stat().st_size
    if file_size <= 0:
        raise SplatError(SPLAT_PLY_INVALID, "The Gaussian PLY is empty.")
    if file_size > max_artifact_bytes:
        raise SplatError(
            SPLAT_ARTIFACT_TOO_LARGE, "The Gaussian PLY exceeds the configured size limit."
        )

    digest = hashlib.sha256()
    # Hash and validate in one pass over the same file handle to prove that the
    # bytes measured are the bytes that will be registered.
    with target.open("rb") as handle:
        header = _read_header(handle)
        degree = header.sh_degree
        if sh_degree is not None and degree != sh_degree:
            raise SplatError(
                SPLAT_PLY_INVALID,
                f"The Gaussian PLY uses SH degree {degree}, expected {sh_degree}.",
            )
        expected = splat_ply_properties(degree)
        if header.properties != expected:
            raise SplatError(
                SPLAT_PLY_INVALID,
                "The Gaussian PLY does not match the pinned Nerfstudio property order.",
            )
        if header.vertex_count > max_gaussians:
            raise SplatError(
                SPLAT_ARTIFACT_TOO_LARGE, "The Gaussian PLY declares too many Gaussians."
            )
        expected_size = header.data_offset + header.vertex_count * header.bytes_per_vertex
        if file_size != expected_size:
            raise SplatError(
                SPLAT_PLY_INVALID,
                "The Gaussian PLY size does not match its declared vertex count.",
            )

        handle.seek(0)
        position = 0
        while True:
            block = handle.read(1024 * 1024)
            if not block:
                break
            digest.update(block)
            position += len(block)
        if position != file_size:
            raise SplatError(SPLAT_PLY_INVALID, "The Gaussian PLY changed while it was read.")

        handle.seek(header.data_offset)
        min_position = np.full(3, np.inf, dtype=np.float64)
        max_position = np.full(3, -np.inf, dtype=np.float64)
        scale_min = np.inf
        scale_max = -np.inf
        opacity_min = np.inf
        opacity_max = -np.inf
        quaternion_min = np.inf
        for block in _chunks(handle, header):
            names = block.dtype.names or ()
            for name in names:
                values = block[name]
                if not np.all(np.isfinite(values)):
                    raise SplatError(
                        SPLAT_PLY_INVALID, "The Gaussian PLY contains non-finite values."
                    )
            xyz = np.stack([block["x"], block["y"], block["z"]], axis=1).astype(np.float64)
            if np.max(np.abs(xyz)) > _MAX_ABS_POSITION:
                raise SplatError(
                    SPLAT_PLY_INVALID, "The Gaussian PLY contains implausible positions."
                )
            min_position = np.minimum(min_position, xyz.min(axis=0))
            max_position = np.maximum(max_position, xyz.max(axis=0))

            scales = np.stack([block["scale_0"], block["scale_1"], block["scale_2"]], axis=1)
            if scales.min() < _MIN_LOG_SCALE or scales.max() > _MAX_LOG_SCALE:
                raise SplatError(SPLAT_PLY_INVALID, "The Gaussian PLY contains implausible scales.")
            scale_min = min(scale_min, float(scales.min()))
            scale_max = max(scale_max, float(scales.max()))

            opacity = block["opacity"].astype(np.float64)
            if opacity.min() < _MIN_LOGIT_OPACITY or opacity.max() > _MAX_LOGIT_OPACITY:
                raise SplatError(
                    SPLAT_PLY_INVALID, "The Gaussian PLY contains implausible opacity."
                )
            opacity_min = min(opacity_min, float(opacity.min()))
            opacity_max = max(opacity_max, float(opacity.max()))

            quats = np.stack(
                [block["rot_0"], block["rot_1"], block["rot_2"], block["rot_3"]], axis=1
            ).astype(np.float64)
            norms = np.linalg.norm(quats, axis=1)
            if norms.min() < _MIN_QUATERNION_NORM or norms.max() > _MAX_QUATERNION_NORM:
                raise SplatError(
                    SPLAT_PLY_INVALID, "The Gaussian PLY contains invalid rotation quaternions."
                )
            quaternion_min = min(quaternion_min, float(norms.min()))

    warnings: list[str] = []
    if degree != 3:
        warnings.append("SPLAT_SH_DEGREE_NOT_DEFAULT")
    return SplatPlyValidation(
        path=target,
        sha256=digest.hexdigest(),
        file_size_bytes=file_size,
        gaussian_count=header.vertex_count,
        sh_degree=degree,
        properties=header.properties,
        bounding_box={
            "min": [round(float(value), 6) for value in min_position],
            "max": [round(float(value), 6) for value in max_position],
        },
        scale_log_min=scale_min,
        scale_log_max=scale_max,
        opacity_logit_min=opacity_min,
        opacity_logit_max=opacity_max,
        quaternion_norm_min=quaternion_min,
        warnings=warnings,
    )


def read_splat_ply_header(path: Path) -> SplatPlyHeader:
    """Return the parsed header of a PLY file (used by tests and benchmarks)."""
    with Path(path).open("rb") as handle:
        return _read_header(handle)


def write_splat_ply(
    path: Path,
    *,
    properties: tuple[str, ...],
    values: dict[str, np.ndarray],
    version: str = "1.1.5",
) -> None:
    """Write a binary Gaussian PLY in the pinned Nerfstudio property order.

    A tiny shared writer keeps the test fixture, the exporter and the
    conformance check byte-compatible with the upstream header.
    """
    count = int(next(iter(values.values())).shape[0])
    if any(int(array.shape[0]) != count for array in values.values()):
        raise ValueError("every PLY property must have the same number of values")
    with Path(path).open("wb") as handle:
        handle.write(b"ply\n")
        handle.write(f"format {PLY_FORMAT} {PLY_VERSION}\n".encode())
        handle.write(f"comment Generated by Nerfstudio {version}\n".encode())
        handle.write(b"comment Vertical Axis: z\n")
        handle.write(f"element vertex {count}\n".encode())
        for name in properties:
            handle.write(f"property float {name}\n".encode())
        handle.write(b"end_header\n")
        columns = [np.asarray(values[name], dtype="<f4") for name in properties]
        block = np.stack(columns, axis=1)
        handle.write(block.tobytes(order="C"))


def write_test_splat_ply(
    path: Path,
    *,
    count: int = 64,
    sh_degree: int = 3,
    seed: int = 7,
) -> int:
    """Write a small deterministic, schema-valid Gaussian PLY for tests."""
    rng = np.random.default_rng(seed)
    properties = splat_ply_properties(sh_degree)
    values: dict[str, np.ndarray] = {name: np.zeros(count, dtype=np.float32) for name in properties}
    values["x"] = rng.normal(0.0, 1.0, count).astype(np.float32)
    values["y"] = rng.normal(0.0, 1.0, count).astype(np.float32)
    values["z"] = rng.normal(0.0, 1.0, count).astype(np.float32)
    directions = rng.normal(size=(count, 4)).astype(np.float32)
    directions /= np.linalg.norm(directions, axis=1, keepdims=True)
    for index in range(4):
        values[f"rot_{index}"] = directions[:, index]
    for index in range(3):
        values[f"scale_{index}"] = rng.normal(-2.0, 0.5, count).astype(np.float32)
    values["opacity"] = rng.normal(2.0, 0.7, count).astype(np.float32)
    for index in range(3):
        values[f"f_dc_{index}"] = rng.normal(0.0, 0.5, count).astype(np.float32)
    for index in range(F_REST_PER_DEGREE[sh_degree]):
        values[f"f_rest_{index}"] = rng.normal(0.0, 0.05, count).astype(np.float32)
    write_splat_ply(path, properties=properties, values=values)
    return count


__all__ = [
    "SplatPlyHeader",
    "SplatPlyValidation",
    "read_splat_ply_header",
    "validate_splat_ply",
    "write_splat_ply",
    "write_test_splat_ply",
]
