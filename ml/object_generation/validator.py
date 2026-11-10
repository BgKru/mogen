"""GLB container, structure and geometry validation.

This validator is deliberately independent of trimesh: it parses the binary
glTF container directly and reads the POSITION/COLOR_0/indices accessors, which
is exactly the evidence required by 06_object_generation.md Section 12 and
09_testing.md Section 12. It rejects a file that merely exists but is not a
usable, self-contained glTF 2.0 binary.
"""

from __future__ import annotations

import hashlib
import json
import math
import struct
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .exceptions import GLB_VALIDATION_FAILED, ExportError

GLB_MAGIC = 0x46546C67  # b"glTF"
GLB_VERSION = 2
CHUNK_JSON = 0x4E4F534A
CHUNK_BIN = 0x004E4942

COMPONENT_SIZES = {
    5120: 1,  # BYTE
    5121: 1,  # UNSIGNED_BYTE
    5122: 2,  # SHORT
    5123: 2,  # UNSIGNED_SHORT
    5125: 4,  # UNSIGNED_INT
    5126: 4,  # FLOAT
}
TYPE_COMPONENTS = {
    "SCALAR": 1,
    "VEC2": 2,
    "VEC3": 3,
    "VEC4": 4,
    "MAT2": 4,
    "MAT3": 9,
    "MAT4": 16,
}
INDEX_COMPONENT_TYPES = frozenset({5121, 5123, 5125})
COLOR_COMPONENT_TYPES = frozenset({5121, 5123, 5126})


@dataclass(frozen=True, slots=True)
class GLBValidation:
    """Facts proven by a successful validation (09_testing.md Section 12.7)."""

    file_size_bytes: int
    sha256: str
    meshes_count: int
    primitives_count: int
    vertices_count: int
    faces_count: int
    materials_count: int
    textures_count: int
    has_vertex_colors: bool
    bounding_box: dict[str, float]
    is_watertight: bool = False
    warnings: tuple[str, ...] = field(default_factory=tuple)

    def as_metadata(self) -> dict[str, Any]:
        """Return the JSONB-safe result metadata."""
        return {
            "vertices_count": self.vertices_count,
            "faces_count": self.faces_count,
            "meshes_count": self.meshes_count,
            "primitives_count": self.primitives_count,
            "materials_count": self.materials_count,
            "textures_count": self.textures_count,
            "has_vertex_colors": self.has_vertex_colors,
            "bounding_box": self.bounding_box,
        }


def _invalid(message: str) -> ExportError:
    return ExportError(GLB_VALIDATION_FAILED, message)


def sha256_file(path: Path) -> str:
    """Return the SHA-256 checksum of a file."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _parse_container(data: bytes) -> tuple[dict[str, Any], bytes]:
    """Split a GLB into its JSON document and binary chunk."""
    if len(data) < 20:
        raise _invalid("The GLB file is too small to contain a header and JSON chunk.")
    magic, version, total_length = struct.unpack_from("<III", data, 0)
    if magic != GLB_MAGIC:
        raise _invalid("The file does not start with the GLB magic header.")
    if version != GLB_VERSION:
        raise _invalid(f"Unsupported GLB container version {version}.")
    if total_length != len(data):
        raise _invalid(f"GLB length field {total_length} does not match the file size {len(data)}.")

    offset = 12
    json_document: dict[str, Any] | None = None
    binary_chunk = b""
    while offset < total_length:
        if offset + 8 > total_length:
            raise _invalid("A GLB chunk header extends past the end of the file.")
        chunk_length, chunk_type = struct.unpack_from("<II", data, offset)
        offset += 8
        if chunk_length % 4 != 0:
            raise _invalid("A GLB chunk length is not 4-byte aligned.")
        if offset + chunk_length > total_length:
            raise _invalid("A GLB chunk extends past the end of the file.")
        payload = data[offset : offset + chunk_length]
        offset += chunk_length

        if chunk_type == CHUNK_JSON:
            if json_document is not None:
                raise _invalid("The GLB contains more than one JSON chunk.")
            try:
                json_document = json.loads(payload.decode("utf-8").rstrip("\x00 \t\r\n"))
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise _invalid("The GLB JSON chunk is not valid JSON.") from exc
        elif chunk_type == CHUNK_BIN:
            if binary_chunk:
                raise _invalid("The GLB contains more than one BIN chunk.")
            binary_chunk = payload
        else:
            # Unknown chunk types are permitted by glTF and must be ignored.
            continue

    if json_document is None:
        raise _invalid("The GLB has no JSON chunk.")
    if not binary_chunk:
        raise _invalid("The GLB has no BIN chunk; the asset is not self-contained.")
    return json_document, binary_chunk


def _read_accessor_values(
    document: dict[str, Any],
    binary_chunk: bytes,
    accessor_index: int,
    *,
    expected_type: str | None = None,
    expected_component_types: frozenset[int] | None = None,
) -> tuple[list[tuple[float, ...]], int]:
    """Read an accessor's values as tuples; returns (values, component_type)."""
    accessors = document.get("accessors") or []
    buffer_views = document.get("bufferViews") or []
    if not isinstance(accessors, list) or not isinstance(buffer_views, list):
        raise _invalid("The GLB accessors or bufferViews are malformed.")
    if accessor_index < 0 or accessor_index >= len(accessors):
        raise _invalid(f"Accessor index {accessor_index} is out of range.")

    accessor = accessors[accessor_index]
    if not isinstance(accessor, dict):
        raise _invalid("An accessor is not an object.")
    component_type = accessor.get("componentType")
    component_count = TYPE_COMPONENTS.get(str(accessor.get("type")))
    count = accessor.get("count")
    if component_type not in COMPONENT_SIZES:
        raise _invalid("An accessor uses an unknown component type.")
    if component_count is None:
        raise _invalid("An accessor uses an unknown element type.")
    if not isinstance(count, int) or count < 1:
        raise _invalid("An accessor has a non-positive count.")
    if expected_type is not None and accessor.get("type") != expected_type:
        raise _invalid(f"Expected a {expected_type} accessor, got {accessor.get('type')!r}.")
    if expected_component_types is not None and component_type not in expected_component_types:
        raise _invalid(f"Accessor component type {component_type} is not accepted here.")

    buffer_view_index = accessor.get("bufferView")
    if not isinstance(buffer_view_index, int) or not 0 <= buffer_view_index < len(buffer_views):
        raise _invalid("An accessor references a missing bufferView.")
    view = buffer_views[buffer_view_index]
    if not isinstance(view, dict):
        raise _invalid("A bufferView is not an object.")
    if view.get("buffer") not in (0, None):
        raise _invalid("The GLB references an external buffer; it is not self-contained.")
    view_offset = int(view.get("byteOffset", 0))
    view_length = int(view.get("byteLength", 0))
    if view_offset < 0 or view_length < 0 or view_offset + view_length > len(binary_chunk):
        raise _invalid("A bufferView extends past the BIN chunk.")

    element_size = COMPONENT_SIZES[component_type] * component_count
    stride = int(view.get("byteStride", 0)) or element_size
    accessor_offset = int(accessor.get("byteOffset", 0))
    if accessor_offset < 0:
        raise _invalid("An accessor has a negative byteOffset.")
    if accessor_offset + stride * (count - 1) + element_size > view_length:
        raise _invalid("An accessor extends past its bufferView.")

    fmt_prefix = {5120: "b", 5121: "B", 5122: "h", 5123: "H", 5125: "I", 5126: "f"}[component_type]
    element_format = "<" + fmt_prefix * component_count
    absolute_start = view_offset + accessor_offset
    values: list[tuple[float, ...]] = []
    for index in range(count):
        start = absolute_start + index * stride
        unpacked = struct.unpack_from(element_format, binary_chunk, start)
        values.append(tuple(float(value) for value in unpacked))
    return values, component_type


def _accessor_min_max(accessor: dict[str, Any]) -> tuple[list[float], list[float]] | None:
    minimum = accessor.get("min")
    maximum = accessor.get("max")
    if (
        isinstance(minimum, list)
        and isinstance(maximum, list)
        and len(minimum) == len(maximum) == 3
    ):
        return ([float(value) for value in minimum], [float(value) for value in maximum])
    return None


def validate_glb_bytes(data: bytes) -> GLBValidation:
    """Validate an in-memory GLB and return its structural and geometry facts."""
    document, binary_chunk = _parse_container(data)

    asset = document.get("asset")
    if not isinstance(asset, dict) or str(asset.get("version")) != "2.0":
        raise _invalid("The glTF asset version is missing or not 2.0.")
    scenes = document.get("scenes")
    nodes = document.get("nodes")
    meshes = document.get("meshes")
    accessors = document.get("accessors")
    if not isinstance(scenes, list) or not scenes:
        raise _invalid("The GLB has no scene.")
    if not isinstance(nodes, list) or not nodes:
        raise _invalid("The GLB has no nodes.")
    if not isinstance(meshes, list) or not meshes:
        raise _invalid("The GLB has no mesh.")
    if not isinstance(accessors, list) or not accessors:
        raise _invalid("The GLB has no accessors.")
    if not isinstance(document.get("buffers"), list) or not document["buffers"]:
        raise _invalid("The GLB has no buffer.")
    if document["buffers"][0].get("uri"):
        raise _invalid("The GLB references an external buffer; it is not self-contained.")

    materials = document.get("materials") or []
    textures = document.get("textures") or []
    if not isinstance(materials, list) or not isinstance(textures, list):
        raise _invalid("The GLB materials or textures are malformed.")

    lowest = [math.inf, math.inf, math.inf]
    highest = [-math.inf, -math.inf, -math.inf]
    total_vertices = 0
    total_faces = 0
    primitives_count = 0
    has_vertex_colors = False
    warnings: list[str] = []

    for mesh_index, mesh in enumerate(meshes):
        if not isinstance(mesh, dict):
            raise _invalid(f"Mesh {mesh_index} is not an object.")
        primitives = mesh.get("primitives")
        if not isinstance(primitives, list) or not primitives:
            raise _invalid(f"Mesh {mesh_index} has no primitives.")
        for primitive in primitives:
            primitives_count += 1
            if not isinstance(primitive, dict):
                raise _invalid("A mesh primitive is not an object.")
            attributes = primitive.get("attributes")
            if not isinstance(attributes, dict) or "POSITION" not in attributes:
                raise _invalid("A mesh primitive has no POSITION attribute.")
            position_accessor = attributes["POSITION"]
            if not isinstance(position_accessor, int):
                raise _invalid("POSITION must reference an accessor index.")
            positions, _ = _read_accessor_values(
                document,
                binary_chunk,
                position_accessor,
                expected_type="VEC3",
                expected_component_types=frozenset({5126}),
            )
            if not positions:
                raise _invalid("A POSITION accessor is empty.")
            for position in positions:
                for axis, value in enumerate(position):
                    if not math.isfinite(value):
                        raise _invalid("A mesh contains a non-finite vertex coordinate.")
                    lowest[axis] = min(lowest[axis], value)
                    highest[axis] = max(highest[axis], value)
            accessor = accessors[position_accessor]
            declared = _accessor_min_max(accessor)
            if declared is not None:
                for axis in range(3):
                    if declared[0][axis] > declared[1][axis]:
                        raise _invalid("A POSITION accessor declares an inverted bounding box.")
            else:
                warnings.append("POSITION accessor has no min/max; bounds were computed.")
            total_vertices += len(positions)

            if "COLOR_0" in attributes:
                color_accessor = attributes["COLOR_0"]
                if not isinstance(color_accessor, int):
                    raise _invalid("COLOR_0 must reference an accessor index.")
                colors, color_type = _read_accessor_values(
                    document,
                    binary_chunk,
                    color_accessor,
                    expected_component_types=COLOR_COMPONENT_TYPES,
                )
                if color_type not in COLOR_COMPONENT_TYPES:
                    raise _invalid("COLOR_0 uses an unsupported component type.")
                if len(colors) != len(positions):
                    raise _invalid("COLOR_0 and POSITION accessor counts differ.")
                has_vertex_colors = True

            indices = primitive.get("indices")
            if indices is None:
                total_faces += len(positions) // 3
            else:
                if not isinstance(indices, int):
                    raise _invalid("indices must reference an accessor index.")
                values, _ = _read_accessor_values(
                    document,
                    binary_chunk,
                    indices,
                    expected_type="SCALAR",
                    expected_component_types=INDEX_COMPONENT_TYPES,
                )
                if len(values) % 3 != 0:
                    raise _invalid("The index accessor count is not a multiple of three.")
                position_count = len(positions)
                for (value,) in values:
                    if value < 0 or value >= position_count:
                        raise _invalid("A face index is out of range.")
                total_faces += len(values) // 3

            material_index = primitive.get("material")
            if material_index is not None and (
                not isinstance(material_index, int) or not 0 <= material_index < len(materials)
            ):
                raise _invalid("A primitive references a missing material.")

    if total_vertices < 3 or total_faces < 1:
        raise _invalid("The GLB contains no usable polygon geometry.")
    extents = [highest[axis] - lowest[axis] for axis in range(3)]
    if not all(math.isfinite(extent) and extent > 1e-6 for extent in extents):
        raise _invalid("The GLB bounding box is degenerate.")
    if not has_vertex_colors:
        raise _invalid("The GLB has no COLOR_0 vertex colours (OBJ-AC-10).")

    return GLBValidation(
        file_size_bytes=len(data),
        sha256=hashlib.sha256(data).hexdigest(),
        meshes_count=len(meshes),
        primitives_count=primitives_count,
        vertices_count=total_vertices,
        faces_count=total_faces,
        materials_count=len(materials),
        textures_count=len(textures),
        has_vertex_colors=has_vertex_colors,
        bounding_box={
            "width": round(extents[0], 6),
            "height": round(extents[1], 6),
            "depth": round(extents[2], 6),
        },
        warnings=tuple(warnings),
    )


def validate_glb(path: Path) -> GLBValidation:
    """Validate a GLB on disk and verify the checksum is reproducible."""
    if not path.is_file():
        raise _invalid("The exported GLB does not exist.")
    size = path.stat().st_size
    if size <= 0:
        raise _invalid("The exported GLB is empty.")
    data = path.read_bytes()
    result = validate_glb_bytes(data)
    if result.file_size_bytes != size:
        raise _invalid("The GLB size changed while it was being validated.")
    if result.sha256 != sha256_file(path):
        raise _invalid("The GLB checksum is not reproducible.")
    return result
